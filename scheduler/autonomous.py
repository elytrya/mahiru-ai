"""Инициатива Mahiru: она САМА решает, когда написать первой или глянуть на экран.

НИКАКИХ окон по часам, НИКАКИХ «шансов» и лимитов «N раз в день».
Каждые INITIATIVE_TICK_MINUTES минут собираем контекст и спрашиваем модель:
хочешь сейчас написать? хочешь глянуть на экран? Хочет — делает, не хочет — молчит.
Мягкий предохранитель от спама (INITIATIVE_MIN_GAP_MINUTES) — это НЕ расписание, а просто
чтобы не заваливала сообщениями подряд.
"""
from __future__ import annotations
import json
import re
import datetime as dt

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from db.session import SessionLocal
from db import repo
from db.models import User
from sqlalchemy import select
from ai.prompts import (build_autonomous_prompt, build_date_greeting_prompt,
                        build_life_event_prompt, build_screen_watch_prompt,
                        build_initiative_decision_prompt)
from ai.providers.base import ChatMessage
from utils.weather import get_weather
from utils.screen import capture_screen_jpeg, screen_available
from ai.providers.factory import build_provider
from utils.humanize import dedash
from utils.logger import log


class AutonomousScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self.provider = build_provider()

    def start(self) -> None:
        minutes = max(2, int(getattr(settings, "INITIATIVE_TICK_MINUTES", 20)))
        self.scheduler.add_job(self._tick, IntervalTrigger(minutes=minutes))
        self.scheduler.start()
        log.info(f"Autonomous scheduler started (tick={minutes}m)")

    def shutdown(self) -> None:
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass

    #  Тик: фоновая лента жизни + инициатива по её желанию            #
    async def _tick(self) -> None:
        now = dt.datetime.now()

        # Фон: раз в день придумывает себе событие дня (без часового окна)
        if getattr(settings, "LIFE_FEED_ENABLED", True):
            try:
                await self._make_life_event(now)
            except Exception:
                log.exception("life event tick failed")

        # Инициатива: она сама решает, писать ли / глянуть ли на экран
        autonomous_on = getattr(settings, "AUTONOMOUS_ENABLED", True)
        screen_on = getattr(settings, "SCREEN_WATCH_ENABLED", False)
        if not (autonomous_on or screen_on):
            return
        try:
            await self._initiative(now, autonomous_on, screen_on)
        except Exception:
            log.exception("initiative tick failed")

    #  Вспомогательное                                              #
    async def _minutes_since_last(self, s, user_id: int):
        """(минут с последнего сообщения, роль последнего). created_at хранится в UTC."""
        recent = await repo.recent_messages(s, user_id, limit=1)
        if not recent:
            return (10 ** 6, None)
        last = recent[-1]
        role = getattr(last, "role", None)
        ts = getattr(last, "created_at", None)
        if ts is None:
            return (10 ** 6, role)
        try:
            delta = dt.datetime.utcnow() - ts
            mins = int(max(0, delta.total_seconds() // 60))
        except Exception:
            mins = 10 ** 6
        return (mins, role)

    def _parse_decision(self, raw: str) -> tuple[bool, bool]:
        """Извлекаем {write, screen} из ответа модели (толерантно к мусору)."""
        if not raw:
            return (False, False)
        txt = raw.strip()
        # Попробуем честный JSON
        try:
            m = re.search(r"\{.*\}", txt, re.DOTALL)
            if m:
                obj = json.loads(m.group(0))
                return (bool(obj.get("write")), bool(obj.get("screen")))
        except Exception:
            pass
        # Фоллбэк: ищем паттерны "write": true / "screen": true
        low = txt.lower()
        write = bool(re.search(r"write\D{0,6}(true|1|yes|да)", low))
        screen = bool(re.search(r"screen\D{0,6}(true|1|yes|да)", low))
        return (write, screen)

    async def _initiative(self, now: dt.datetime, autonomous_on: bool,
                          screen_on: bool) -> None:
        """Опрашиваем модель по контексту и действуем по её решению."""
        gap_min = max(0, int(getattr(settings, "INITIATIVE_MIN_GAP_MINUTES", 40)))
        cam_ok = screen_on and screen_available()

        async with SessionLocal() as s:
            res = await s.execute(select(User))
            users = list(res.scalars().all())
            personality = await repo.get_personality(s)

        for u in users:
            try:
                async with SessionLocal() as s:
                    mins, last_role = await self._minutes_since_last(s, u.id)
                    mems = await repo.top_memories(s, u.id, limit=10)
                    recent = await repo.recent_messages(s, u.id, limit=20)
                    last_init_raw = await repo.get_setting(s, f"initiative:last_min:{u.id}")

                # Мягкий антиспам: не чаще чем раз в gap_min минут (по её инициативе)
                if last_init_raw:
                    try:
                        last_init = dt.datetime.fromisoformat(last_init_raw)
                        if (dt.datetime.utcnow() - last_init).total_seconds() < gap_min * 60:
                            continue
                    except Exception:
                        pass

                recent_topics = [
                    (m.content or "").strip()[:80]
                    for m in recent
                    if getattr(m, "role", None) == "user" and (m.content or "").strip()
                ][-6:]

                # Специальное событие сегодня (дата) — отдаём в контекст решения
                special = await self._special_today(u.id, now)

                # Решение модели (только текст, без картинки)
                dprompt = build_initiative_decision_prompt(
                    personality, mins, last_role, recent_topics=recent_topics,
                    special_today=special, screen_available=cam_ok,
                )
                dresp = await self.provider.chat(
                    [ChatMessage("system", dprompt),
                     ChatMessage("user", "Решай сейчас. Только JSON.")],
                    temperature=0.8, max_tokens=40,
                )
                want_write, want_screen = self._parse_decision(dresp.text or "")
                if not autonomous_on:
                    want_write = False
                if not cam_ok:
                    want_screen = False
                if not (want_write or want_screen):
                    continue

                sent = False
                # Сначала экран (она решила подглядеть)
                if want_screen:
                    sent = await self._comment_screen(u, personality, now)
                # Иначе просто напишет первой
                if not sent and want_write:
                    sent = await self._write_first(u, personality, mems,
                                                   recent_topics, special, now)

                if sent:
                    async with SessionLocal() as s:
                        await repo.set_setting(
                            s, f"initiative:last_min:{u.id}",
                            dt.datetime.utcnow().isoformat(),
                        )
            except Exception:
                log.exception("initiative per-user failed")

    async def _special_today(self, user_id: int, now: dt.datetime):
        """Если сегодня памятная дата (ещё не отмечена) — вернём краткое описание."""
        if not getattr(settings, "DATES_ENABLED", True):
            return None
        today = now.date().isoformat()
        async with SessionLocal() as s:
            dates = await repo.dates_on(s, now.month, now.day)
            for d in dates:
                if d.user_id != user_id:
                    continue
                guard = f"date_greeted:{d.id}:{today}"
                if await repo.get_setting(s, guard):
                    continue
                kind_word = {"birthday": "день рождения",
                             "anniversary": "годовщина"}.get(d.kind, "важная дата")
                return f"{kind_word} — {d.title}"
        return None

    #  Действия                                                        #
    async def _write_first(self, u: User, personality, mems, recent_topics,
                           special, now: dt.datetime) -> bool:
        """Написать первой. Если сегодня памятная дата — поздравит."""
        try:
            # Если сегодня дата — превратим в поздравление и пометим дату выполненной
            date_obj = await self._pop_date_for_greeting(u.id, now)
            if date_obj is not None:
                d, years = date_obj
                prompt = build_date_greeting_prompt(personality, d.title, d.kind, years)
                user_line = "Поздравь меня сейчас."
                meta = {"date_greeting": d.id}
            else:
                prompt = build_autonomous_prompt(personality, mems, recent_topics=recent_topics)
                user_line = "Напиши мне первой сейчас."
                meta = {"autonomous": True}
            resp = await self.provider.chat(
                [ChatMessage("system", prompt),
                 ChatMessage("user", user_line)],
                temperature=0.9, max_tokens=200,
            )
            text = dedash((resp.text or "").strip())
            if not text:
                return False
            await self.bot.send_message(u.tg_id, text)
            async with SessionLocal() as s:
                await repo.add_message(s, u.id, "assistant", text, meta=meta)
            return True
        except Exception:
            log.exception("write_first failed")
            return False

    async def _pop_date_for_greeting(self, user_id: int, now: dt.datetime):
        """Если есть неотмеченная дата на сегодня — помечаем её и возвращаем (date, years)."""
        if not getattr(settings, "DATES_ENABLED", True):
            return None
        today = now.date().isoformat()
        async with SessionLocal() as s:
            dates = await repo.dates_on(s, now.month, now.day)
            for d in dates:
                if d.user_id != user_id:
                    continue
                guard = f"date_greeted:{d.id}:{today}"
                if await repo.get_setting(s, guard):
                    continue
                await repo.set_setting(s, guard, "1")
                years = None
                if d.year:
                    y = now.year - int(d.year)
                    years = y if y > 0 else None
                return (d, years)
        return None

    async def _comment_screen(self, u: User, personality, now: dt.datetime) -> bool:
        """Сама заглянула на экран и живо прокомментировала. Нужен vision-провайдер."""
        try:
            shot = capture_screen_jpeg()
            if not shot:
                log.info("screen watch: экран недоступен - пропускаю")
                return False
            prompt = build_screen_watch_prompt(personality)
            resp = await self.provider.chat(
                [ChatMessage("system", prompt),
                 ChatMessage("user", "Посмотри, что у меня сейчас на экране, и отреагируй.",
                             images=[shot])],
                temperature=0.9, max_tokens=200,
            )
            text = dedash((resp.text or "").strip())
            if not text:
                return False
            await self.bot.send_message(u.tg_id, text)
            async with SessionLocal() as s:
                await repo.add_message(s, u.id, "assistant", text,
                                       meta={"screen_watch": now.date().isoformat()})
            return True
        except Exception:
            log.exception("screen watch send failed")
            return False

    async def _make_life_event(self, now: dt.datetime) -> None:
        """Раз в день придумывает себе бытовое событие дня (лента жизни, фон).

        Не отправляется пользователю — хранится в Setting и всплывает в контексте,
        чтобы Махиру могла невзначай упомянуть свой день в переписке.
        Без часового окна: первый тик за день — и готово.
        """
        today = now.date().isoformat()
        async with SessionLocal() as s:
            if await repo.get_setting(s, f"life_event_done:{today}"):
                return
            personality = await repo.get_personality(s)
        city = (getattr(settings, "MAHIRU_CITY", "") or "").strip() or "своём городе"
        wdesc = ""
        try:
            w = await get_weather(city if city != "своём городе" else None)
            if w:
                wdesc = w.get("desc", "")
        except Exception:
            pass
        try:
            prompt = build_life_event_prompt(personality, city, wdesc)
            resp = await self.provider.chat(
                [ChatMessage("system", prompt),
                 ChatMessage("user", "Что у тебя сегодня случилось за день?")],
                temperature=0.95, max_tokens=80,
            )
            raw = (resp.text or "").strip()
            event = dedash(raw.splitlines()[0].strip()) if raw else ""
            event = event.strip('"').strip("'").strip()
            if not event:
                return
            async with SessionLocal() as s:
                await repo.set_setting(s, "life_event:text", event)
                await repo.set_setting(s, "life_event:date", today)
                await repo.set_setting(s, f"life_event_done:{today}", "1")
            log.info(f"\U0001f4d4 лента жизни: {event!r}")
        except Exception:
            log.exception("life event generate failed")

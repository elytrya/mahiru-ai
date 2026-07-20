from __future__ import annotations
import random
import datetime as dt

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from db.session import SessionLocal
from db import repo
from db.models import User
from sqlalchemy import select
from ai.prompts import build_autonomous_prompt, build_date_greeting_prompt, build_weather_care_prompt
from ai.providers.base import ChatMessage
from utils.weather import get_weather
from ai.providers.factory import build_provider
from utils.humanize import dedash
from utils.logger import log

class AutonomousScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self.provider = build_provider()

    def start(self) -> None:
        self.scheduler.add_job(self._tick, IntervalTrigger(minutes=60))  # раз в час тыкаем
        self.scheduler.start()
        log.info("Autonomous scheduler started")

    def shutdown(self) -> None:
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass

    async def _tick(self) -> None:
        now = dt.datetime.now()

        # памятные даты — проверяем раз в день в заданный час (поздравляет сама)
        if getattr(settings, "DATES_ENABLED", True) and now.hour == int(getattr(settings, "DATES_GREET_HOUR", 10)):
            try:
                await self._greet_dates(now)
            except Exception:
                log.exception("date greeting tick failed")

        # погода-забота - раз в день в СЛУЧАЙНОЕ время («там у тебя дождь, возьми зонт»)
        # час не фиксирован - сам выбирается внутри _greet_weather, поэтому тыкаем каждый тик
        if getattr(settings, "WEATHER_ENABLED", True):
            try:
                await self._greet_weather(now)
            except Exception:
                log.exception("weather care tick failed")

        if not (settings.AUTONOMOUS_TIME_START <= now.hour < settings.AUTONOMOUS_TIME_END):
            return
        p_write = 1.0 / max(settings.AUTONOMOUS_MIN_HOURS, 1)
        if random.random() > p_write:
            return

        async with SessionLocal() as s:
            res = await s.execute(select(User))
            users = list(res.scalars().all())
            personality = await repo.get_personality(s)

        for u in users:
            try:
                async with SessionLocal() as s:
                    mems = await repo.top_memories(s, u.id, limit=10)
                    recent = await repo.recent_messages(s, u.id, limit=20)
                # инициатива: сама вспоминает недавние темы разговора
                recent_topics = [
                    (m.content or "").strip()[:80]
                    for m in recent
                    if getattr(m, "role", None) == "user" and (m.content or "").strip()
                ][-6:]
                prompt = build_autonomous_prompt(personality, mems, recent_topics=recent_topics)
                resp = await self.provider.chat(
                    [ChatMessage("system", prompt),
                     ChatMessage("user", "Напиши мне первой сейчас.")],
                    temperature=0.9, max_tokens=200,
                )
                text = dedash((resp.text or "").strip())
                if text:
                    await self.bot.send_message(u.tg_id, text)
                    async with SessionLocal() as s:
                        await repo.add_message(s, u.id, "assistant", text,
                                               meta={"autonomous": True})
            except Exception:
                log.exception("autonomous send failed")

    async def _weather_due(self, now: dt.datetime) -> bool:
        """Каждый день выбираем СЛУЧАЙНЫЙ час (в окне WEATHER_MIN_HOUR..WEATHER_MAX_HOUR),
        чтобы писала про погоду в разное время, а не по будильнику."""
        today = now.date().isoformat()
        key = f"weather_day_hour:{today}"
        async with SessionLocal() as s:
            raw = await repo.get_setting(s, key)
        if raw is None:
            lo = int(getattr(settings, "WEATHER_MIN_HOUR", 8))
            hi = int(getattr(settings, "WEATHER_MAX_HOUR", 22))
            if hi < lo:
                lo, hi = 8, 22
            target = random.randint(lo, hi)
            async with SessionLocal() as s:
                await repo.set_setting(s, key, str(target))
        else:
            try:
                target = int(raw)
            except (TypeError, ValueError):
                target = 8
        return now.hour >= target

    async def _greet_weather(self, now: dt.datetime) -> None:
        """Забота про погоду: сама напишет про погоду в городе владельца, раз в день в случайное время."""
        # ещё не наступил случайный час на сегодня - ждём
        if not await self._weather_due(now):
            return
        w = await get_weather()
        if not w:
            return  # нет ключа/города или API не ответил
        today = now.date().isoformat()
        async with SessionLocal() as s:
            personality = await repo.get_personality(s)
            res = await s.execute(select(User))
            users = list(res.scalars().all())
        for u in users:
            guard = f"weather_greeted:{u.id}:{today}"
            async with SessionLocal() as s:
                if await repo.get_setting(s, guard):
                    continue
            try:
                prompt = build_weather_care_prompt(
                    personality, w.get("city", ""), w.get("desc", ""),
                    w.get("temp"), w.get("advice", ""),
                )
                resp = await self.provider.chat(
                    [ChatMessage("system", prompt),
                     ChatMessage("user", "Напиши мне про погоду сейчас.")],
                    temperature=0.9, max_tokens=200,
                )
                text = dedash((resp.text or "").strip())
                if text:
                    await self.bot.send_message(u.tg_id, text)
                    async with SessionLocal() as s:
                        await repo.add_message(s, u.id, "assistant", text,
                                               meta={"weather_care": today})
                        await repo.set_setting(s, guard, "1")
            except Exception:
                log.exception("weather care send failed")

    async def _greet_dates(self, now: dt.datetime) -> None:
        """Поздравляет с днями рождения/годовщинами, один раз в день на каждую дату."""
        today = now.date().isoformat()
        async with SessionLocal() as s:
            personality = await repo.get_personality(s)
            dates = await repo.dates_on(s, now.month, now.day)
        if not dates:
            return
        async with SessionLocal() as s:
            res = await s.execute(select(User))
            users = {u.id: u for u in res.scalars().all()}
        for d in dates:
            u = users.get(d.user_id)
            if not u:
                continue
            guard = f"date_greeted:{d.id}:{today}"
            async with SessionLocal() as s:
                if await repo.get_setting(s, guard):
                    continue
            years = None
            if d.year:
                y = now.year - int(d.year)
                years = y if y > 0 else None
            try:
                prompt = build_date_greeting_prompt(personality, d.title, d.kind, years)
                resp = await self.provider.chat(
                    [ChatMessage("system", prompt),
                     ChatMessage("user", "Поздравь меня сейчас.")],
                    temperature=0.9, max_tokens=200,
                )
                text = dedash((resp.text or "").strip())
                if text:
                    await self.bot.send_message(u.tg_id, text)
                    async with SessionLocal() as s:
                        await repo.add_message(s, u.id, "assistant", text,
                                               meta={"date_greeting": d.id})
                        await repo.set_setting(s, guard, "1")
            except Exception:
                log.exception("date greeting failed")

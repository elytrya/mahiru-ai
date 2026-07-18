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
from ai.prompts import build_autonomous_prompt
from ai.providers.base import ChatMessage
from ai.providers.factory import build_provider
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
                prompt = build_autonomous_prompt(personality, mems)
                resp = await self.provider.chat(
                    [ChatMessage("system", prompt),
                     ChatMessage("user", "Напиши мне первой сейчас.")],
                    temperature=0.9, max_tokens=200,
                )
                text = (resp.text or "").strip()
                if text:
                    await self.bot.send_message(u.tg_id, text)
                    async with SessionLocal() as s:
                        await repo.add_message(s, u.id, "assistant", text,
                                               meta={"autonomous": True})
            except Exception:
                log.exception("autonomous send failed")

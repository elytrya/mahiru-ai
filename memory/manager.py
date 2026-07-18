from __future__ import annotations
import re

from sqlalchemy.ext.asyncio import AsyncSession

from db import repo
from db.models import Memory
from memory import storage, analyzer
from ai.providers.base import BaseProvider
from utils.logger import log

MIN_IMPORTANCE_TO_SAVE = 60

def _score(query: str, m: Memory) -> float:
    q = set(re.findall(r"\w+", query.lower()))
    f = set(re.findall(r"\w+", m.fact.lower()))
    overlap = len(q & f)
    return overlap * 2.0 + m.importance / 100.0

class MemoryManager:
    async def retrieve(self, session: AsyncSession, user_id: int, query: str,
                       k: int = 8) -> list[Memory]:
        top = await repo.top_memories(session, user_id, limit=50)
        ranked = sorted(top, key=lambda m: _score(query, m), reverse=True)
        return ranked[:k]

    async def observe(self, session: AsyncSession, user_id: int,
                      user_text: str, bot_text: str, provider: BaseProvider) -> None:
        if len(user_text.strip()) < 6:
            return
        candidates = await analyzer.extract(provider, user_text, bot_text)
        for c in candidates:
            try:
                imp = int(c.get("importance", 0))
            except Exception:
                imp = 0
            if imp < MIN_IMPORTANCE_TO_SAVE:
                continue
            await storage.save(session, user_id,
                               fact=c["fact"][:500],
                               category=(c.get("category") or "fact")[:64],
                               importance=imp,
                               source="chat")
            log.debug(f"remembered ({imp}): {c['fact']!r}")

    async def clear(self, session: AsyncSession, user_id: int) -> int:
        return await storage.clear(session, user_id)

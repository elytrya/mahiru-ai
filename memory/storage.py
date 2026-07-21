"""Хранение и выборка воспоминаний в БД."""
from __future__ import annotations
import re
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import repo
from db.models import Memory

_WORD_RE = re.compile(r"[\wа-яА-ЯёЁ]+", re.IGNORECASE)

def _normalize(fact: str) -> str:
    return " ".join(_WORD_RE.findall((fact or "").lower()))

def _jaccard(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

async def _find_duplicate(session: AsyncSession, user_id: int, fact: str) -> Memory | None:
    norm_new = _normalize(fact)
    if not norm_new:
        return None
    res = await session.execute(
        select(Memory).where(Memory.user_id == user_id).order_by(Memory.id.desc()).limit(50)
    )
    for m in res.scalars():
        if _jaccard(norm_new, _normalize(m.fact)) >= 0.75:
            return m
    return None

async def save(session: AsyncSession, user_id: int, fact: str,
               category: str, importance: int, source: str = "chat"):
    dup = await _find_duplicate(session, user_id, fact)
    if dup:
        if importance > dup.importance:
            dup.importance = importance
            await session.commit()
            await session.refresh(dup)
        return dup
    return await repo.add_memory(session, user_id, fact, category, importance, source)

async def top(session: AsyncSession, user_id: int, limit: int = 20):
    return await repo.top_memories(session, user_id, limit=limit)

async def clear(session: AsyncSession, user_id: int) -> int:
    return await repo.clear_memory(session, user_id)

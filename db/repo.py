from __future__ import annotations
import datetime as dt
from typing import Sequence

from sqlalchemy import select, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, Personality, Memory, Message, MoodState, Setting

async def upsert_user(session: AsyncSession, tg_id: int, username: str | None,
                     first_name: str | None) -> User:
    res = await session.execute(select(User).where(User.tg_id == tg_id))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(tg_id=tg_id, username=username, first_name=first_name)
        session.add(user)
    else:
        user.username = username
        user.first_name = first_name
        user.last_seen = dt.datetime.utcnow()
    await session.commit()
    await session.refresh(user)
    return user

async def get_personality(session: AsyncSession) -> Personality:
    res = await session.execute(select(Personality).where(Personality.id == 1))
    p = res.scalar_one_or_none()
    if p is None:
        p = Personality(id=1)
        session.add(p)
        await session.commit()
        await session.refresh(p)
    return p

async def update_personality(session: AsyncSession, **fields) -> Personality:
    p = await get_personality(session)
    for k, v in fields.items():
        if hasattr(p, k):
            setattr(p, k, v)
    p.updated_at = dt.datetime.utcnow()
    await session.commit()
    await session.refresh(p)
    return p

async def add_message(session: AsyncSession, user_id: int, role: str,
                     content: str, meta: dict | None = None) -> None:
    session.add(Message(user_id=user_id, role=role, content=content, meta=meta))
    await session.commit()

async def recent_messages(session: AsyncSession, user_id: int, limit: int = 20) -> list[Message]:
    res = await session.execute(
        select(Message).where(Message.user_id == user_id)
        .order_by(desc(Message.created_at)).limit(limit)
    )
    return list(reversed(list(res.scalars().all())))

async def get_mood(session: AsyncSession, user_id: int) -> MoodState:
    res = await session.execute(select(MoodState).where(MoodState.user_id == user_id))
    m = res.scalar_one_or_none()
    if m is None:
        m = MoodState(user_id=user_id)
        session.add(m)
        await session.commit()
        await session.refresh(m)
    return m

async def set_mood(session: AsyncSession, user_id: int, mood: str,
                   intensity: float = 0.5) -> MoodState:
    m = await get_mood(session, user_id)
    m.mood = mood
    m.intensity = intensity
    m.updated_at = dt.datetime.utcnow()
    await session.commit()
    await session.refresh(m)
    return m

async def add_memory(session: AsyncSession, user_id: int, fact: str,
                     category: str, importance: int, source: str = "chat") -> Memory:
    mem = Memory(user_id=user_id, fact=fact, category=category,
                 importance=importance, source=source)
    session.add(mem)
    await session.commit()
    await session.refresh(mem)
    return mem

async def top_memories(session: AsyncSession, user_id: int, limit: int = 15) -> list[Memory]:
    res = await session.execute(
        select(Memory).where(Memory.user_id == user_id)
        .order_by(desc(Memory.importance), desc(Memory.created_at)).limit(limit)
    )
    return list(res.scalars().all())

async def clear_memory(session: AsyncSession, user_id: int) -> int:
    res = await session.execute(delete(Memory).where(Memory.user_id == user_id))
    await session.commit()
    return res.rowcount or 0

async def get_setting(session: AsyncSession, key: str, default: str | None = None) -> str | None:
    res = await session.execute(select(Setting).where(Setting.key == key))
    row = res.scalar_one_or_none()
    return row.value if row else default

async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.execute(select(Setting).where(Setting.key == key))
    obj = row.scalar_one_or_none()
    if obj:
        obj.value = value
    else:
        session.add(Setting(key=key, value=value))
    await session.commit()

async def all_user_ids(session: AsyncSession) -> Sequence[int]:
    res = await session.execute(select(User.id))
    return [row[0] for row in res.all()]

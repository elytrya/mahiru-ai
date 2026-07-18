from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from db import repo

async def load_personality(session: AsyncSession):
    return await repo.get_personality(session)

async def update_field(session: AsyncSession, field: str, value):
    return await repo.update_personality(session, **{field: value})

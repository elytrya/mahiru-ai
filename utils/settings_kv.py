from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import SessionLocal
from db import repo
from config import settings

def _kv_key(name: str) -> str:
    return "api:" + name.strip().upper()

async def get_key(name: str, default: str | None = None,
                  session: AsyncSession | None = None) -> str | None:
    upper = name.strip().upper()
    v = getattr(settings, upper, None)
    if v:
        return v

    async def _lookup(s):
        return await repo.get_setting(s, _kv_key(upper))

    if session is not None:
        val = await _lookup(session)
    else:
        async with SessionLocal() as s:
            val = await _lookup(s)
    return val or default

async def set_key(name: str, value: str,
                  session: AsyncSession | None = None) -> None:
    upper = name.strip().upper()
    if session is not None:
        await repo.set_setting(session, _kv_key(upper), value)
    else:
        async with SessionLocal() as s:
            await repo.set_setting(s, _kv_key(upper), value)
    if hasattr(settings, upper):
        try:
            setattr(settings, upper, value)
        except Exception:
            pass

async def delete_key(name: str, session: AsyncSession | None = None) -> None:
    upper = name.strip().upper()
    if session is not None:
        await repo.set_setting(session, _kv_key(upper), "")
    else:
        async with SessionLocal() as s:
            await repo.set_setting(s, _kv_key(upper), "")
    if hasattr(settings, upper):
        try:
            setattr(settings, upper, None)
        except Exception:
            pass

async def load_overrides() -> int:
    n = 0
    async with SessionLocal() as s:
        for field in list(settings.__class__.model_fields.keys()):
            v = await repo.get_setting(s, _kv_key(field))
            if v:
                try:
                    setattr(settings, field, v)
                    n += 1
                except Exception:
                    pass
    return n

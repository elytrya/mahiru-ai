"""Чтение и запись настроек и ключей в БД, поля поведения."""
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

_SECRET_SUFFIXES = ("_API_KEY", "_KEY", "_TOKEN", "_SECRET")
_SECRET_EXTRA = {"YANDEX_FOLDER", "YANDEX_PROMPT_ID", "G4F_PROVIDER"}

def _is_secret_field(field: str) -> bool:
    up = field.upper()
    return up.endswith(_SECRET_SUFFIXES) or up in _SECRET_EXTRA

async def load_overrides() -> int:
    n = 0
    async with SessionLocal() as s:
        for field in list(settings.__class__.model_fields.keys()):
            if not _is_secret_field(field):
                continue
            v = await repo.get_setting(s, _kv_key(field))
            if v:
                try:
                    setattr(settings, field, v)
                    n += 1
                except Exception:
                    pass
    return n


BEHAVIOR_FIELDS = (
    "NO_EMDASH",
    "HUMAN_TYPING",
    "TYPING_SPEED_CPS",
    "TYPING_MIN_SECONDS",
    "TYPING_MAX_SECONDS",
    "READ_DELAY_MIN",
    "READ_DELAY_MAX",
    "IGNORE_CHANCE",
    "IGNORE_MIN_SECONDS",
    "IGNORE_MAX_SECONDS",
    "SPLIT_MESSAGES",
    "SPLIT_MAX",
    "TYPING_INDICATOR",
    "SHOW_TOOL_CALLS",
    "REACTIONS_ENABLED",
    "REACTION_CHANCE",
    "TYPO_ENABLED",
    "TYPO_CHANCE",
    "MOOD_SPEED_ENABLED",
    "READ_SILENCE_ENABLED",
    "READ_SILENCE_CHANCE",
    "READ_SILENCE_MIN_SECONDS",
    "READ_SILENCE_MAX_SECONDS",
    "STICKERS_ENABLED",
    "STICKER_CHANCE",
    "DATES_ENABLED",
    "DATES_GREET_HOUR",
    "JEALOUSY_ENABLED",
    "JEALOUSY_HOURS",
    "ENERGY_ENABLED",
    "CLOSENESS_ENABLED",
    "CLOSENESS_PER_MSG",
    "PETNAMES_ENABLED",
    "PETNAME_THRESHOLD",
    "WEATHER_ENABLED",
    "WEATHER_CITY",
    "WEATHER_CARE_HOUR",
    "WEATHER_UNITS",
    "WEATHER_LANG",
)

_TRUE_WORDS = ("1", "true", "yes", "on", "да", "+", "вкл", "y")

def _beh_key(name: str) -> str:
    return "beh:" + name.strip().upper()

def _coerce(field: str, raw):
    """Приводит строку из БД/команды к типу текущего значения в settings."""
    cur = getattr(settings, field, None)
    s = str(raw).strip()
    if isinstance(cur, bool):
        return s.lower() in _TRUE_WORDS
    if isinstance(cur, int) and not isinstance(cur, bool):
        return int(float(s.replace(",", ".")))
    if isinstance(cur, float):
        return float(s.replace(",", "."))
    return s

def apply_behavior(field: str, raw) -> None:
    up = field.strip().upper()
    if not hasattr(settings, up):
        return
    try:
        setattr(settings, up, _coerce(up, raw))
    except Exception:
        pass

async def set_behavior(name: str, value,
                       session: AsyncSession | None = None) -> None:
    up = name.strip().upper()
    val = "true" if value is True else "false" if value is False else str(value)
    if session is not None:
        await repo.set_setting(session, _beh_key(up), val)
    else:
        async with SessionLocal() as s:
            await repo.set_setting(s, _beh_key(up), val)
    apply_behavior(up, val)

async def get_behavior(name: str,
                       session: AsyncSession | None = None) -> str | None:
    up = name.strip().upper()
    if session is not None:
        return await repo.get_setting(session, _beh_key(up))
    async with SessionLocal() as s:
        return await repo.get_setting(s, _beh_key(up))

async def load_behavior_overrides() -> int:
    n = 0
    async with SessionLocal() as s:
        for field in BEHAVIOR_FIELDS:
            v = await repo.get_setting(s, _beh_key(field))
            if v is not None and v != "":
                apply_behavior(field, v)
                n += 1
    return n

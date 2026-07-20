"""Стикеры / кастом-эмодзи по настроению.

Храним набор id в БД (Setting["stickers:json"]) как JSON вида:
    {"any": ["id1", "id2"], "loving": [...], "playful": [...], ...}

id может быть двух типов:
  * чисто цифровой (напр. 6365185259734040633) - это custom_emoji_id, отправляется
    как сообщение с custom_emoji-entity (премиум-эмодзи);
  * иначе (CAACAgI...) - это file_id обычного стикера/гифки.

Всё настраивается: STICKERS_ENABLED / STICKER_CHANCE + команда /sticker.
"""
from __future__ import annotations
import json
import random

from config import settings
from db.session import SessionLocal
from db import repo

_STICKERS_KEY = "stickers:json"

# настроения, для которых можно держать отдельные наборы (+ "any" = общий)
MOOD_SLOTS = ("any", "happy", "sad", "tired", "excited",
              "curious", "annoyed", "playful", "loving")


def is_custom_emoji(sid: str) -> bool:
    """Чисто цифровой id -> это custom_emoji_id."""
    return sid.isdigit()


def _defaults() -> dict[str, list[str]]:
    raw = (getattr(settings, "STICKER_IDS_DEFAULT", "") or "").strip()
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    return {"any": ids} if ids else {}


async def _load_raw(session=None) -> dict[str, list[str]]:
    async def _get(s):
        return await repo.get_setting(s, _STICKERS_KEY)
    if session is not None:
        val = await _get(session)
    else:
        async with SessionLocal() as s:
            val = await _get(s)
    if not val:
        return _defaults()
    try:
        data = json.loads(val)
        if isinstance(data, dict):
            # нормализуем к spisok[str]
            return {k: [str(x) for x in v] for k, v in data.items()
                    if isinstance(v, list)}
    except Exception:
        pass
    return _defaults()


async def _save_raw(data: dict[str, list[str]], session=None) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    if session is not None:
        await repo.set_setting(session, _STICKERS_KEY, payload)
    else:
        async with SessionLocal() as s:
            await repo.set_setting(s, _STICKERS_KEY, payload)


async def get_all(session=None) -> dict[str, list[str]]:
    return await _load_raw(session)


async def add_sticker(slot: str, sid: str, session=None) -> bool:
    slot = (slot or "any").strip().lower()
    sid = sid.strip()
    if not sid:
        return False
    data = await _load_raw(session)
    lst = data.setdefault(slot, [])
    if sid in lst:
        return False
    lst.append(sid)
    await _save_raw(data, session)
    return True


async def del_sticker(slot: str, sid: str, session=None) -> bool:
    slot = (slot or "any").strip().lower()
    sid = sid.strip()
    data = await _load_raw(session)
    lst = data.get(slot, [])
    if sid in lst:
        lst.remove(sid)
        await _save_raw(data, session)
        return True
    return False


async def pick(mood: str | None = None, session=None) -> str | None:
    """Выбирает id стикера/эмодзи под настроение (или из общего)."""
    data = await _load_raw(session)
    pool: list[str] = []
    if mood and mood in data:
        pool += data.get(mood, [])
    pool += data.get("any", [])
    if not pool:
        return None
    return random.choice(pool)


async def send(msg, mood: str | None = None, session=None) -> bool:
    """Отправляет случайный стикер/эмодзи под настроение. True если отправила."""
    sid = await pick(mood, session)
    if not sid:
        return False
    try:
        if is_custom_emoji(sid):
            from aiogram.types import MessageEntity
            placeholder = "🌸"  # видимый глиф заменится кастом-эмодзи
            await msg.answer(
                placeholder,
                entities=[MessageEntity(type="custom_emoji", offset=0,
                                        length=len(placeholder),
                                        custom_emoji_id=sid)],
            )
        else:
            await msg.answer_sticker(sid)
        return True
    except Exception:
        return False

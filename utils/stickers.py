"""Стикеры / кастом-эмодзи по настроению.

Храним набор id в БД (Setting["stickers:json"]) как JSON вида:
    {"any": ["id1", "id2"], "loving": [...], "playful": [...], ...}

id может быть двух типов:
  * чисто цифровой (напр. 6365185259734040633) - это custom_emoji_id, отправляется
    как сообщение с custom_emoji-entity (премиум-эмодзи);
  * иначе (CAACAgI...) - это file_id обычного стикера/гифки.

Всё настраивается: STICKERS_ENABLED / STICKER_CHANCE
/sticker - команда для настойки
"""
from __future__ import annotations
import json
import random
import re

from config import settings
from db.session import SessionLocal
from db import repo

_STICKERS_KEY = "stickers:json"

MOOD_SLOTS = ("any", "happy", "sad", "tired", "excited",
              "curious", "annoyed", "playful", "loving")

_EMOJI_BY_MOOD = {
    "happy":   ["😊", "☺️", "🌸", "✨", "😄"],
    "sad":     ["🥺", "😔", "🌧", "😢", "💧"],
    "tired":   ["😴", "🥱", "😪", "🌙"],
    "excited": ["🤩", "✨", "🔥", "😆", "🎉"],
    "curious": ["🤔", "👀", "🧐", "❓"],
    "annoyed": ["😤", "🙄", "😑", "💢"],
    "playful": ["😜", "😏", "🤭", "😝", "😹"],
    "loving":  ["🥰", "❤️", "😘", "💕", "🌷"],
    "any":     ["🌸", "✨", "💕", "😊"],
}

_SIT_RULES = [
    ("loving",  re.compile(r"(любл|обожа|скуча|мой хорош|родн|цел(ую|овать)|обнима|❤|🥰|😘|💕)", re.I)),
    ("playful", re.compile(r"(хаха|ахах|хих|шучу|прикол|ору\b|\bлол\b|😹|😜|😏|подмигн)", re.I)),
    ("sad",     re.compile(r"(груст|плак|обидно|жаль|расстро|😢|😔|🥺)", re.I)),
    ("excited", re.compile(r"(ура|класс|супер|обалден|восторг|не могу дожд|🔥|🤩|🎉)", re.I)),
    ("annoyed", re.compile(r"(бесит|злюсь|надоел|раздража|\bфу\b|😤|🙄|💢)", re.I)),
    ("tired",   re.compile(r"(устал|спать|вымот|сонн|зева|😴|🥱)", re.I)),
    ("curious", re.compile(r"(интересно|расскажи|правда\?|как так|а что|🤔|👀)", re.I)),
]


def mood_from_text(text: str) -> str | None:
    """Определяет ситуацию по тексту ответа Mahiru (для подбора стикера)."""
    if not text:
        return None
    for mood, rx in _SIT_RULES:
        if rx.search(text):
            return mood
    return None


def pick_emoji(mood: str | None = None) -> str:
    """Живой эмодзи под настроение (гарантированно отправляется, без премиума)."""
    pool = list(_EMOJI_BY_MOOD.get(mood or "", [])) + _EMOJI_BY_MOOD["any"]
    return random.choice(pool)


def is_custom_emoji(sid: str) -> bool:
    """Чисто цифровой id -> это custom_emoji_id."""
    return sid.isdigit()


def _defaults() -> dict[str, list[str]]:
    raw = (getattr(settings, "STICKER_IDS_DEFAULT", "") or "").strip()
    ids = [x.strip() for x in raw.split(",") if x.strip()]
    return {"any": ids} if ids else {}


async def _load_raw(session=None, with_defaults: bool = True) -> dict[str, list[str]]:
    async def _get(s):
        return await repo.get_setting(s, _STICKERS_KEY)
    if session is not None:
        val = await _get(session)
    else:
        async with SessionLocal() as s:
            val = await _get(s)
    empty: dict[str, list[str]] = _defaults() if with_defaults else {}
    if not val:
        return empty
    try:
        data = json.loads(val)
        if isinstance(data, dict):
            return {k: [str(x) for x in v] for k, v in data.items()
                    if isinstance(v, list)}
    except Exception:
        pass
    return empty


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
    data = await _load_raw(session, with_defaults=False)
    lst = data.setdefault(slot, [])
    if sid in lst:
        return False
    lst.append(sid)
    await _save_raw(data, session)
    return True


async def add_many(slot: str, sids: list[str], session=None) -> int:
    """Добавляет сразу много id (целый пак) в одно настроение. Возвращает число добавленных."""
    slot = (slot or "any").strip().lower()
    data = await _load_raw(session, with_defaults=False)
    lst = data.setdefault(slot, [])
    added = 0
    for sid in sids:
        sid = str(sid).strip()
        if sid and sid not in lst:
            lst.append(sid)
            added += 1
    if added:
        await _save_raw(data, session)
    return added


async def del_sticker(slot: str, sid: str, session=None) -> bool:
    slot = (slot or "any").strip().lower()
    sid = sid.strip()
    data = await _load_raw(session, with_defaults=False)
    lst = data.get(slot, [])
    if sid in lst:
        lst.remove(sid)
        await _save_raw(data, session)
        return True
    return False


async def clear_slot(slot: str, session=None) -> int:
    """Очищает набор стикеров одного настроения. Возвращает, сколько удалила."""
    slot = (slot or "any").strip().lower()
    data = await _load_raw(session, with_defaults=False)
    n = len(data.get(slot, []))
    data[slot] = []
    await _save_raw(data, session)
    return n


async def disable_defaults(session=None) -> None:
    """Сохраняет пустую структуру, чтобы дефолтный цветочек больше не подставлялся."""
    data = await _load_raw(session, with_defaults=False)
    await _save_raw(data, session)


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
    """Отправляет стикер/кастом-эмодзи под ситуацию. Если не вышло - живой эмодзи."""
    sid = await pick(mood, session)
    if sid:
        try:
            if is_custom_emoji(sid):
                from aiogram.types import MessageEntity
                placeholder = "🌸"
                u16 = len(placeholder.encode("utf-16-le")) // 2
                await msg.answer(
                    placeholder,
                    entities=[MessageEntity(type="custom_emoji", offset=0,
                                            length=u16, custom_emoji_id=sid)],
                )
            else:
                await msg.answer_sticker(sid)
            return True
        except Exception:
            pass
    if getattr(settings, "STICKER_EMOJI_FALLBACK", True):
        try:
            await msg.answer(pick_emoji(mood))
            return True
        except Exception:
            return False
    return False

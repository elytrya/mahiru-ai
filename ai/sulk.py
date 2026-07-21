"""Режим обиды/игнора.

После прямого оскорбления Махиру обижается и больше НЕ отвечает,
пока не извинятся (или пока сама не остынет через SULK_MAX_HOURS).

Состояние храним в таблице Setting как JSON: {"since": iso-utc, "strikes": int}.
"""
from __future__ import annotations

import json
import datetime as dt

from db import repo
from config import settings
from utils.logger import log

_KEY = "sulk:{uid}"

_COOLDOWN_MULT = {3: 0.4, 2: 0.7, 1: 1.0, 0: 1.6}


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


async def _load(session, user_id: int) -> dict | None:
    raw = await repo.get_setting(session, _KEY.format(uid=user_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


async def _effective_max_hours(session, user_id: int) -> float:
    """Время остывания с учётом близости: близким короче, чужим дольше."""
    base = float(getattr(settings, "SULK_MAX_HOURS", 24.0))
    if base <= 0:
        return base
    try:
        from ai.context import closeness_level
        u = await repo.get_user(session, user_id)
        lvl = closeness_level(int(getattr(u, "closeness", 0) or 0)) if u else 0
        return base * _COOLDOWN_MULT.get(lvl, 1.0)
    except Exception:
        return base


async def is_sulking(session, user_id: int) -> bool:
    """Обижена ли сейчас. Автоматически остывает через SULK_MAX_HOURS."""
    st = await _load(session, user_id)
    if not st:
        return False
    try:
        since = dt.datetime.fromisoformat(st.get("since"))
        max_h = await _effective_max_hours(session, user_id)
        if max_h > 0 and (_now() - since).total_seconds() >= max_h * 3600:
            await clear(session, user_id)
            log.info("\U0001f54a обида сама прошла по времени")
            return False
    except Exception:
        pass
    return True


async def enter(session, user_id: int) -> int:
    """Войти в обиду (или продлить). Возвращает счётчик оскорблений."""
    st = await _load(session, user_id) or {"strikes": 0}
    st["strikes"] = int(st.get("strikes", 0)) + 1
    st["since"] = _now().isoformat()
    await repo.set_setting(session, _KEY.format(uid=user_id),
                           json.dumps(st, ensure_ascii=False))
    return st["strikes"]


async def clear(session, user_id: int) -> None:
    """Сбросить обиду (помирились)."""
    await repo.set_setting(session, _KEY.format(uid=user_id), "")


async def apply_penalty(session, user_id: int, strikes: int = 1) -> int:
    """Снижает близость за грубость (сильнее при повторах). Возвращает списанные очки."""
    if not getattr(settings, "CLOSENESS_ENABLED", True):
        return 0
    base = int(getattr(settings, "SULK_CLOSENESS_PENALTY", 3) or 0)
    if base <= 0:
        return 0
    pen = base * min(max(int(strikes), 1), 3)
    u = await repo.get_user(session, user_id)
    cur = int(getattr(u, "closeness", 0) or 0) if u else 0
    pen = min(pen, cur)
    if pen > 0:
        await repo.bump_closeness(session, user_id, -pen)
    return pen

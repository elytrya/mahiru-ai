"""Динамический контекст характера Махиру для каждого ответа.

Собирает блок «ситуация прямо сейчас», который влияет на тон:
- уровень близости (тёплый тон разблокируется со временем),
- ласковое прозвище (пет-нейм),
- ревность/обидка (если долго не писал),
- энергия/батарейка (к ночи устаёт).
"""
from __future__ import annotations

import datetime as dt

from config import settings

# пороги близости -> уровень 0..3
_CLOSENESS_LEVELS = [(80, 3), (30, 2), (10, 1), (0, 0)]

_CLOSE_HINT = {
    0: "вы ещё только знакомитесь: тёпло, но немного стеснительно, без чрезмерной ласки",
    1: "ты уже привыкла к нему: чуть теплее и свободнее в общении",
    2: "вы близки: можно ласковый тон, шутки, лёгкий флирт, забота",
    3: "вы очень близки: максимально нежный и тёплый тон, много заботы и ласки",
}


def closeness_level(points: int) -> int:
    for thr, lvl in _CLOSENESS_LEVELS:
        if (points or 0) >= thr:
            return lvl
    return 0


def _fmt_gap(seconds: float) -> str:
    """Человеческая длительность паузы (без тире)."""
    h = seconds / 3600.0
    if h >= 48:
        return f"{int(h // 24)} дн."
    if h >= 1:
        return f"{int(h)} ч."
    return f"{max(1, int(seconds // 60))} мин."


def _energy_hint(hour: int) -> str:
    if 23 <= hour or hour < 6:
        return (
            "сейчас поздняя ночь, ты устала и клонит в сон: пиши короче, "
            "мягче и ленивее, больше нежности и меньше энергии"
        )
    if 21 <= hour < 23:
        return "вечер, ты уже немного устала: тон спокойнее и мягче, чуть короче"
    if 6 <= hour < 9:
        return "раннее утро, ты только проснулась: немного сонная, но ласковая"
    return ""


def build_dynamic_context(user, last_user_ts: dt.datetime | None, now: dt.datetime | None = None) -> str | None:
    """Собирает список подсказок-строк. Возвращает текст или None.

    last_user_ts ожидается в UTC (как Message.created_at). Час энергии — локальный.
    """
    now_local = now or dt.datetime.now()
    parts: list[str] = []

    # уровень близости
    if getattr(settings, "CLOSENESS_ENABLED", True) and user is not None:
        pts = int(getattr(user, "closeness", 0) or 0)
        lvl = closeness_level(pts)
        parts.append(f"Близость: уровень {lvl}/3 ({pts} очк.). {_CLOSE_HINT[lvl]}.")

    # ласковое прозвище
    if getattr(settings, "PETNAMES_ENABLED", True) and user is not None and getattr(user, "pet_name", None):
        parts.append(
            f"Ты ласково зовёшь его '{user.pet_name}'. Иногда обращайся так (не в каждом сообщении, а к месту)."
        )

    # ревность/обидка
    if getattr(settings, "JEALOUSY_ENABLED", True) and last_user_ts is not None:
        gap = (dt.datetime.utcnow() - last_user_ts).total_seconds()
        threshold = float(getattr(settings, "JEALOUSY_HOURS", 12.0)) * 3600.0
        if gap >= threshold:
            parts.append(
                f"Он не писал тебе уже {_fmt_gap(gap)}. Встреть его с лёгкой обидой/ревностью "
                "в начале («ну наконец-то появился», «а я тут скучала»), но без злобы и быстро оттай."
            )

    # энергия/батарейка
    if getattr(settings, "ENERGY_ENABLED", True):
        e = _energy_hint(now_local.hour)
        if e:
            parts.append(f"Энергия: {e}.")

    if not parts:
        return None
    return "\n".join(f"- {p}" for p in parts)

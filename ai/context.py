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


def build_dynamic_context(user, last_user_ts: dt.datetime | None, now: dt.datetime | None = None,
                          *, life_event: str | None = None,
                          open_thread: str | None = None) -> str | None:
    """Собирает список подсказок-строк. Возвращает текст или None.

    last_user_ts ожидается в UTC (как Message.created_at). Час энергии — локальный.
    life_event - событие дня (лента жизни); open_thread - незакрытая тема разговора.
    """
    now_local = now or dt.datetime.now()
    parts: list[str] = []

    if getattr(settings, "CLOSENESS_ENABLED", True) and user is not None:
        pts = int(getattr(user, "closeness", 0) or 0)
        lvl = closeness_level(pts)
        parts.append(f"Близость: уровень {lvl}/3 ({pts} очк.). {_CLOSE_HINT[lvl]}.")

    if getattr(settings, "PETNAMES_ENABLED", True) and user is not None and getattr(user, "pet_name", None):
        parts.append(
            f"Ты ласково зовёшь его '{user.pet_name}'. Иногда обращайся так (не в каждом сообщении, а к месту)."
        )

    if getattr(settings, "JEALOUSY_ENABLED", True) and last_user_ts is not None:
        gap = (dt.datetime.utcnow() - last_user_ts).total_seconds()
        threshold = float(getattr(settings, "JEALOUSY_HOURS", 12.0)) * 3600.0
        if gap >= threshold:
            parts.append(
                f"Он не писал тебе уже {_fmt_gap(gap)}. Встреть его с лёгкой обидой/ревностью "
                "в начале («ну наконец-то появился», «а я тут скучала»), но без злобы и быстро оттай."
            )

    if getattr(settings, "RETURN_NOTE_ENABLED", True) and last_user_ts is not None:
        gap = (dt.datetime.utcnow() - last_user_ts).total_seconds()
        jeal = float(getattr(settings, "JEALOUSY_HOURS", 12.0)) * 3600.0
        rmin = float(getattr(settings, "RETURN_MIN_HOURS", 3.0)) * 3600.0
        if rmin <= gap < jeal:
            h = now_local.hour
            if 5 <= h < 11:
                note = "утром - сонно и ласково ('о, доброе утро, соня', 'проснулся наконец')"
            elif h >= 23 or h < 5:
                note = "поздней ночью - 'ты чего не спишь?', 'я уж сама спать собиралась'"
            else:
                note = "тепло отметь, что он пропадал ('ну наконец появился', 'а я тут скучала')"
            parts.append(
                f"Он не писал {_fmt_gap(gap)} и только что вернулся. Встреть живо по времени суток: {note}. Без допроса."
            )

    if getattr(settings, "ENERGY_ENABLED", True):
        e = _energy_hint(now_local.hour)
        if e:
            parts.append(f"Энергия: {e}.")

    if life_event:
        parts.append(
            f"Твоё сегодняшнее событие дня: {life_event}. Можешь невзначай упомянуть это к слову, "
            "как живой человек делится своим днём (не выдумывай лишних деталей)."
        )

    if open_thread:
        parts.append(
            f"Ранее он упоминал: {open_thread}. Если к месту, живо и БЕЗ допроса спроси ОДНИМ вопросом, "
            "как оно прошло ('слушай, а как... прошло-то?') - искренне, один раз."
        )

    if not parts:
        return None
    return "\n".join(f"- {p}" for p in parts)

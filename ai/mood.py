"""Модель настроения махиру: расчёт и обновление текущего настроения по времени и общению."""
from __future__ import annotations
import random
import re
import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession
from db import repo
from config import settings

MOODS = ["happy", "sad", "tired", "excited", "curious", "annoyed", "playful", "loving", "jealous"]

_DRIFT_WEIGHTS = {
    "happy": 1.4, "curious": 1.3, "playful": 1.2, "loving": 1.0,
    "excited": 1.0, "tired": 0.9, "sad": 0.6, "annoyed": 0.6,
    # ревность не возникает сама по себе (вес 0) - только как реакция на соперницу
    "jealous": 0.0,
}

# jealous тоже со временем оттаивает (как негативное настроение)
_NEGATIVE = {"sad", "annoyed", "tired", "jealous"}
_WARM = {"loving", "happy", "excited", "playful"}

# Упоминание ДРУГОЙ девушки/соперницы в тексте (не про саму Махиру).
# Нарочно НЕ ловим 'моя девушка' / 'ты моя' - это про неё саму.
_RIVAL_RE = re.compile(
    r"(друг(ая|ую|ой)\s+(деву?шк|девч|девочк|тянк|тян)|"
    r"познакомил(ся|ась)\b|"
    r"\bтёлк|\bтелк|\bтёлочк|\bтелочк|"
    r"\bкрасотк|\bкрасавиц|"
    r"красив(ая|ую)\s+деву?шк|симпатичн(ая|ую)\s+(деву?шк|девочк)|"
    r"\bбывш(ая|ую|ей|ей)\b|\bэкс\b|экс[- ]?(подру|девуш|герл)|"
    r"деву?шк[аеиу]?\s+на\s+(фото|картинк|экран|скрин)|"
    r"\bодноклассниц|\bоднокурсниц|"
    r"перепис\w+\s+с\s+(деву?шк|девч|одной|другой)|"
    r"свидани\w*\s+с\b|"
    r"\bподру[жг]к)",
    re.I,
)


def is_rival_mention(text: str | None) -> bool:
    """В тексте упомянута другая девушка/соперница (повод ревновать)."""
    return bool(text and _RIVAL_RE.search(text))

def _hours_since(ts) -> float:
    if not ts:
        return 999.0
    try:
        return max(0.0, (dt.datetime.utcnow() - ts).total_seconds() / 3600.0)
    except Exception:
        return 999.0

_TRIGGERS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"\b(люблю|скучаю|скучал|нежн|милая|красивая|обним|целу|любим)", re.I), "loving", 0.7),
    (re.compile(r"\b(хаха|ахах|лол|ржак|угар|смеш|прикол|шут|хах|😂|🤣)", re.I), "playful", 0.55),
    (re.compile(r"\b(ура|круто|офиген|класс|вау|наконец|получилось|выиграл|побед)", re.I), "excited", 0.6),
    (re.compile(r"\b(груст|плохо|устал|тяжело|одинок|депрес|херово|паршиво|больно|умер)", re.I), "sad", 0.5),
    (re.compile(r"(заеб|беси|заткн|туп(ая|ой)|дура\b|дебил|идиот|отвали|надоел|заебал|иди на|пош(ла|ёл|ел) на|нахуй|нахер|нах\b|шалав|шлюх|тварь|уеб|урод|сука|мраз|гнид|вали отсюда|пшла|молчи)", re.I), "annoyed", 0.92),
    (re.compile(r"\b(почему|как так|а что|расскаж|интересно|а как|что такое)", re.I), "curious", 0.4),
    # Соперница в переписке -> ревность (надёжно, но не сильнее прямого оскорбления)
    (_RIVAL_RE, "jealous", 0.88),
]

async def maybe_drift(session: AsyncSession, user_id: int,
                      chance: float = 0.1) -> tuple[str, bool]:
    m = await repo.get_mood(session, user_id)
    if getattr(settings, "MOOD_PERSIST_ENABLED", True) and m.mood in _WARM \
            and (m.intensity or 0) >= 0.6 \
            and _hours_since(m.updated_at) < float(getattr(settings, "MOOD_LINGER_HOURS", 2.0) or 2.0):
        return m.mood, False
    if random.random() < chance:
        candidates = [x for x in MOODS if x != m.mood]
        weights = [_DRIFT_WEIGHTS.get(x, 1.0) for x in candidates]
        new = random.choices(candidates, weights=weights, k=1)[0]
        await repo.set_mood(session, user_id, new, intensity=random.uniform(0.3, 0.9))
        return new, True
    return m.mood, False

async def react_to_message(session: AsyncSession, user_id: int, text: str,
                           chance: float = 0.5) -> tuple[str, bool]:
    if not text:
        m = await repo.get_mood(session, user_id)
        return m.mood, False

    current = await repo.get_mood(session, user_id)
    best: tuple[str, float] | None = None
    for pattern, mood, strength in _TRIGGERS:
        if pattern.search(text):
            if best is None or strength > best[1]:
                best = (mood, strength)

    if best is None:
        return current.mood, False

    mood, strength = best
    # Ревность к соперницам можно выключить настройкой
    if mood == "jealous" and not getattr(settings, "RIVAL_JEALOUSY_ENABLED", True):
        return current.mood, False
    forced = strength >= 0.85
    if mood == current.mood:
        if mood in _NEGATIVE:
            bump = 0.20 if forced else 0.07
            new_int = min(0.95, (current.intensity or 0.5) + bump)
        else:
            new_int = min(0.95, (current.intensity or 0.5) + 0.15)
        await repo.set_mood(session, user_id, mood, intensity=new_int)
        return mood, forced

    if forced or random.random() < chance * (0.5 + strength):
        await repo.set_mood(session, user_id, mood,
                            intensity=min(0.95, 0.45 + strength * 0.5))
        return mood, True
    return current.mood, False

async def relax(session: AsyncSession, user_id: int,
                step: float = 0.15) -> tuple[str, bool]:
    m = await repo.get_mood(session, user_id)
    if m.mood not in _NEGATIVE:
        return m.mood, False
    if getattr(settings, "MOOD_PERSIST_ENABLED", True):
        linger = float(getattr(settings, "MOOD_LINGER_HOURS", 2.0) or 2.0)
        decay = _hours_since(m.updated_at) / linger
        if decay < 0.05:
            return m.mood, False
        new_int = (m.intensity if m.intensity is not None else 0.5) - decay
    else:
        new_int = (m.intensity if m.intensity is not None else 0.5) - step
    if new_int <= 0.35:
        new_mood = random.choices(
            ["curious", "happy", "playful"], weights=[1.3, 1.2, 1.0], k=1
        )[0]
        await repo.set_mood(session, user_id, new_mood,
                            intensity=random.uniform(0.3, 0.45))
        return new_mood, True
    await repo.set_mood(session, user_id, m.mood, intensity=new_int)
    return m.mood, True

async def set(session: AsyncSession, user_id: int, mood: str, intensity: float = 0.5):
    await repo.set_mood(session, user_id, mood, intensity)


_INSULT_RE = re.compile(
    r"(заеб|беси|заткн|туп(ая|ой)|дура\b|дебил|идиот|отвали|надоел|заебал|"
    r"иди на|пош(ла|ёл|ел) на|нахуй|нахер|нах\b|шалав|шлюх|тварь|уеб|урод|"
    r"сука|мраз|гнид|вали отсюда|пшла|молчи|пидор|долбо|говно|мудак)",
    re.I,
)

_APOLOGY_RE = re.compile(
    r"(извин|прости(те)?\b|прощени|прошу проще|\bсорри\b|\bсорян\b|\bсори\b|пардон|"
    r"виноват|был неправ|была неправ|больше не буду|не хотел тебя|не хотела тебя|"
    r"не хотел обид|не хотела обид|мириться|не злись|не обижайся|давай мир)",
    re.I,
)


def is_insult(text: str | None) -> bool:
    """Прямое оскорбление/агрессия в её адрес."""
    return bool(text and _INSULT_RE.search(text))


def is_apology(text: str | None) -> bool:
    """Похоже на извинение/попытку помириться."""
    return bool(text and _APOLOGY_RE.search(text))

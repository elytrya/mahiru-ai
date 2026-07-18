from __future__ import annotations
import random
import re

from sqlalchemy.ext.asyncio import AsyncSession
from db import repo

# все настроения что есть
MOODS = ["happy", "sad", "tired", "excited", "curious", "annoyed", "playful", "loving"]

_DRIFT_WEIGHTS = {
    "happy": 1.4, "curious": 1.3, "playful": 1.2, "loving": 1.0,
    "excited": 1.0, "tired": 0.9, "sad": 0.6, "annoyed": 0.6,
}

_NEGATIVE = {"sad", "annoyed", "tired"}

_TRIGGERS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"\b(люблю|скучаю|скучал|нежн|милая|красивая|обним|целу|любим)", re.I), "loving", 0.7),
    (re.compile(r"\b(хаха|ахах|лол|ржак|угар|смеш|прикол|шут|хах|😂|🤣)", re.I), "playful", 0.55),
    (re.compile(r"\b(ура|круто|офиген|класс|вау|наконец|получилось|выиграл|побед)", re.I), "excited", 0.6),
    (re.compile(r"\b(груст|плохо|устал|тяжело|одинок|депрес|херово|паршиво|больно|умер)", re.I), "sad", 0.5),
    (re.compile(r"\b(заеб|беси|заткн|тупая|дура|отвали|надоел|заебал|иди на|молчи)", re.I), "annoyed", 0.8),
    (re.compile(r"\b(почему|как так|а что|расскаж|интересно|а как|что такое)", re.I), "curious", 0.4),
]

async def maybe_drift(session: AsyncSession, user_id: int,
                      chance: float = 0.1) -> tuple[str, bool]:
    m = await repo.get_mood(session, user_id)
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
    if mood == current.mood:
        if mood in _NEGATIVE:
            new_int = min(0.8, (current.intensity or 0.5) + 0.07)
        else:
            new_int = min(0.95, (current.intensity or 0.5) + 0.15)
        await repo.set_mood(session, user_id, mood, intensity=new_int)
        return mood, False

    if random.random() < chance * (0.5 + strength):
        await repo.set_mood(session, user_id, mood,
                            intensity=min(0.95, 0.4 + strength * 0.5))
        return mood, True
    return current.mood, False

async def relax(session: AsyncSession, user_id: int,
                step: float = 0.15) -> tuple[str, bool]:
    m = await repo.get_mood(session, user_id)
    if m.mood not in _NEGATIVE:
        return m.mood, False
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

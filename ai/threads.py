"""Нити разговора: Махиру помнит незакрытые темы/планы и сама возвращается к ним.

Храним в таблице Setting как JSON-список (без миграций схемы).
Каждая нить: {"text": str, "ts": iso-utc, "asked": bool}.
"""
from __future__ import annotations

import json
import datetime as dt

from db import repo
from ai.providers.base import ChatMessage
from utils.logger import log

_KEY = "open_threads:{uid}"
_MAX = 5


async def get_threads(session, user_id: int) -> list[dict]:
    raw = await repo.get_setting(session, _KEY.format(uid=user_id))
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def _save(session, user_id: int, threads: list[dict]) -> None:
    await repo.set_setting(
        session, _KEY.format(uid=user_id),
        json.dumps(threads[-_MAX:], ensure_ascii=False),
    )


async def extract(session, user_id: int, user_text: str, provider) -> None:
    """Иногда вытаскивает 'незакрытую нить' - план/дело, о котором он упомянул."""
    text = (user_text or "").strip()
    if len(text) < 6:
        return
    prompt = (
        "Из сообщения пользователя-МУЖЧИНЫ вытащи ОДНО незакрытое дело/план на будущее, "
        "о котором потом естественно спросить 'как прошло?'. Примеры: собеседование, экзамен, "
        "поход к врачу, свидание, дедлайн, поездка, важный звонок. Если такого нет - ответь строго 'NONE'. "
        "Иначе ответь ОДНОЙ короткой фразой от лица наблюдателя: "
        "'у него завтра собеседование', 'он сдаёт проект на неделе'. Без кавычек, без пояснений."
    )
    try:
        resp = await provider.chat(
            [ChatMessage("system", prompt), ChatMessage("user", text[:500])],
            tools=None, temperature=0.3, max_tokens=60,
        )
    except Exception:
        log.exception("open-thread extract упал")
        return
    line = ""
    if resp and (resp.text or "").strip():
        line = resp.text.strip().splitlines()[0].strip()
    line = line.strip('"').strip("'").strip()
    if not line or line.upper().startswith("NONE") or len(line) < 6:
        return
    threads = await get_threads(session, user_id)
    low = line.lower()
    for t in threads:
        ex = (t.get("text") or "").lower()
        if ex and (low[:20] in ex or ex[:20] in low):
            return
    threads.append({"text": line, "ts": dt.datetime.utcnow().isoformat(), "asked": False})
    await _save(session, user_id, threads)
    log.info(f"\U0001f9f5 новая нить разговора: {line!r}")


async def due_thread(session, user_id: int, min_hours: float = 8.0) -> dict | None:
    """Нить, о которой пора спросить (прошло время, ещё не спрашивала)."""
    threads = await get_threads(session, user_id)
    now = dt.datetime.utcnow()
    for t in threads:
        if t.get("asked"):
            continue
        try:
            ts = dt.datetime.fromisoformat(t["ts"])
        except Exception:
            continue
        if (now - ts).total_seconds() >= float(min_hours) * 3600.0:
            return t
    return None


async def mark_asked(session, user_id: int, text: str) -> None:
    threads = await get_threads(session, user_id)
    changed = False
    for t in threads:
        if t.get("text") == text and not t.get("asked"):
            t["asked"] = True
            changed = True
    if changed:
        await _save(session, user_id, threads)

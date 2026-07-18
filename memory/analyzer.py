from __future__ import annotations
import json
import re

from ai.providers.base import BaseProvider, ChatMessage
from utils.logger import log

_PROMPT = (
    "Ты — memory extractor. Извлеки только важные долгосрочные факты про пользователя "
    "(предпочтения, био, события, отношения, любимые аниме/мангу и т.д.).\n"
    "Не сохраняй обычные реплики и болтовню.\n"
    "Ответь JSON-массивом: "
    '[{"fact":"...","category":"preference|fact|event|emotion|relationship",'
    '"importance":0-100}]. Если нечего запоминать — верни [].'
)

async def extract(provider: BaseProvider, user_text: str, bot_text: str) -> list[dict]:
    dialog = f"USER: {user_text}\nBOT: {bot_text}"
    try:
        resp = await provider.chat(
            [ChatMessage("system", _PROMPT), ChatMessage("user", dialog)],
            temperature=0.1, max_tokens=400,
        )
    except Exception as e:
        log.warning(f"memory extract failed: {e}")
        return []
    text = (resp.text or "").strip()
    m = re.search(r"\[.*\]", text, re.S)
    raw = m.group(0) if m else text
    try:
        data = json.loads(raw)
        return [x for x in data if isinstance(x, dict) and x.get("fact")]
    except Exception:
        return []

"""Инструмент: поиск в Google (Custom Search)."""
from __future__ import annotations
import httpx

from methods.base import Tool
from utils.cache import cache_get, cache_set
from utils.settings_kv import get_key

class GoogleSearchTool(Tool):
    name = "google_search"
    description = (
        "Поиск в интернете через Google Custom Search (нужен GOOGLE_API_KEY + GOOGLE_CX). "
        "Если ключа нет — вызови web_search (без ключей) или request_api_key."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Поисковый запрос"},
            "num":   {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
        },
        "required": ["query"],
    }

    async def run(self, args, *, session, user_id: int):
        q = (args.get("query") or "").strip()
        if not q:
            return {"results": []}
        num = int(args.get("num", 3))
        ck = f"gsearch:{q}:{num}"
        cached = await cache_get(ck)
        if cached:
            return cached

        api_key = await get_key("GOOGLE_API_KEY", session=session)
        cx = await get_key("GOOGLE_CX", session=session)
        if not api_key or not cx:
            return {"error": "no_google_key",
                    "hint": "вызови request_api_key(service='google') или web_search"}

        params = {"key": api_key, "cx": cx, "q": q, "num": num}
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://www.googleapis.com/customsearch/v1", params=params)
            r.raise_for_status()
            data = r.json()

        results = [{"title": i.get("title"), "link": i.get("link"),
                    "snippet": i.get("snippet")}
                   for i in data.get("items", [])]
        out = {"query": q, "results": results}
        await cache_set(ck, out, ttl=600)
        return out

"""Инструмент: поиск тайтлов в *Lib."""
from __future__ import annotations
from typing import Any

from methods.base import Tool
from methods.lib.client import api_get, LibError
from utils.cache import cache_get, cache_set
from utils.logger import log

_KINDS = {"manga", "ranobe", "hentai"}
_HOSTS = {"manga": "mangalib.me", "ranobe": "ranobelib.me", "hentai": "hentailib.me"}

class LibSearchTool(Tool):
    name = "lib_search"
    description = (
        "Поиск манги/ранобэ/хентая на MangaLib/RanobeLib/HentaiLib. "
        "Обязательно вызови это перед lib_info / lib_download, чтобы получить slug."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "название тайтла для поиска"},
            "kind": {
                "type": "string",
                "enum": ["manga", "ranobe", "hentai"],
                "description": "manga=манга/манхва, ranobe=ранобэ, hentai=18+",
                "default": "manga",
            },
            "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20},
        },
        "required": ["query"],
    }

    async def run(self, args: dict[str, Any], *, session=None, user_id: int = 0) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"error": "query пуст"}
        kind = str(args.get("kind") or "manga").lower()
        limit = args.get("limit", 8)
        if kind not in _KINDS:
            return {"error": f"kind должен быть manga/ranobe/hentai, а не {kind!r}"}
        limit = max(1, min(int(limit or 8), 20))
        ck = f"libsearch:{kind}:{query.lower().strip()}:{limit}"
        cached = await cache_get(ck)
        if cached is not None:
            return cached

        try:
            data = await api_get(kind, "/api/manga", params={
                "q": query,
                "fields[]": ["rate_avg", "rate", "releaseDate"],
            })
        except LibError as e:
            log.warning(f"lib_search {kind} failed: {e}")
            return {"error": str(e)}

        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return {"error": f"нет данных от API: {str(data)[:200]}"}

        host = _HOSTS[kind]
        out: list[dict[str, Any]] = []
        for it in items[:limit]:
            if not isinstance(it, dict):
                continue
            cover = ""
            cv = it.get("cover") or {}
            if isinstance(cv, dict):
                cover = cv.get("default") or cv.get("thumbnail") or ""
            slug = it.get("slug_url") or it.get("slug") or ""
            t = it.get("type")
            status = it.get("status")
            rating = it.get("rating")
            out.append({
                "slug": slug,
                "name": it.get("rus_name") or it.get("name") or it.get("eng_name"),
                "eng_name": it.get("eng_name"),
                "type": t.get("label") if isinstance(t, dict) else t,
                "status": status.get("label") if isinstance(status, dict) else status,
                "year": it.get("releaseDate") or it.get("releaseDateString"),
                "rating": rating.get("average") if isinstance(rating, dict) else it.get("rate_avg"),
            })

        result = {
            "kind": kind,
            "count": len(out),
            "items": out,
            "_hint": "Ты живая девушка, НЕ поисковик. НЕ выводи список, НЕ пиши ссылки/url/обложки. По-человечески скажи что нашла (1-2 тайтла по названию), добавь своё отношение и веди диалог: спроси, ту ли имел в виду и хочет ли почитать/скачать. Скачивание запустится кнопками само.",
        }
        if out and user_id:
            try:
                from handlers import lib_download as _ld
                _ld._LAST_QUERY[user_id] = (kind, query)
            except Exception:
                pass
        await cache_set(ck, result, ttl=300)
        return result

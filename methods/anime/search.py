"""Инструмент: поиск аниме."""
from __future__ import annotations
import re
import httpx

from methods.base import Tool
from utils.cache import cache_get, cache_set

SHIKI_BASE = "https://shikimori.one/api"
SHIKI_UA = "MahiruBot/1.0"

GENRE_MAP = {
    "комедия": 4, "comedy": 4,
    "романтика": 22, "romance": 22,
    "драма": 8, "drama": 8,
    "сейнен": 42, "seinen": 42,
    "сьонен": 27, "shounen": 27, "шонен": 27,
    "фэнтези": 10, "fantasy": 10,
    "приключения": 2, "adventure": 2,
    "экшн": 1, "боевик": 1, "action": 1,
    "повседневность": 36, "slice of life": 36,
    "ужасы": 14, "horror": 14,
    "фантастика": 24, "sci-fi": 24,
    "меха": 18, "mecha": 18,
    "спорт": 30, "sports": 30,
    "триллер": 41, "thriller": 41,
    "детектив": 7, "mystery": 7,
}

def _strip(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"\[/?[a-z0-9=_# ]+\]", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()

class AnimeSearchTool(Tool):
    name = "anime_search"
    description = (
        "Поиск аниме по названию и/или жанру (Shikimori). Вызывай когда надо подобрать "
        "список тайтлов — напр. «что посмотреть про вампиров». Для конкретного аниме бери anime_info."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Ключевые слова (любой язык)"},
            "genre": {"type": "string", "description": "Жанр по-русски или по-английски"},
        },
    }

    async def run(self, args, *, session, user_id: int):
        q = (args.get("query") or "").strip() or None
        g_name = (args.get("genre") or "").strip().lower() or None
        g_id = GENRE_MAP.get(g_name) if g_name else None

        ck = f"shiki:search:{q}:{g_id}"
        cached = await cache_get(ck)
        if cached:
            return cached

        params = {"limit": 5, "order": "popularity"}
        if q:
            params["search"] = q
        if g_id:
            params["genre"] = g_id

        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(SHIKI_BASE + "/animes", params=params,
                                headers={"User-Agent": SHIKI_UA,
                                         "Accept": "application/json"})
                r.raise_for_status()
                data = r.json() or []
        except Exception as e:
            return {"error": "api unavailable", "detail": f"{type(e).__name__}: {e}",
                    "hint": "Предложи тайтлы по своей памяти, если знаешь подходящие."}

        results = []
        for m in data:
            image = ((m.get("image") or {}).get("original")
                     or (m.get("image") or {}).get("preview"))
            if image and image.startswith("/"):
                image = "https://shikimori.one" + image
            results.append({
                "id":       m.get("id"),
                "title":    m.get("russian") or m.get("name"),
                "title_original": m.get("name"),
                "score":    m.get("score"),
                "episodes": m.get("episodes") or m.get("episodes_aired"),
                "kind":     m.get("kind"),
                "aired":    m.get("aired_on"),
                "cover":    image,
                "url":      "https://shikimori.one/animes/" + str(m.get("id", "")),
            })
        out = {"results": results, "source": "shikimori"}
        if not results:
            out["hint"] = "Ничего не нашлось — предложи варианты сама."
        await cache_set(ck, out, ttl=1800)
        return out

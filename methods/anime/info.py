from __future__ import annotations
import re
import httpx

from methods.base import Tool
from utils.cache import cache_get, cache_set

SHIKI_BASE = "https://shikimori.one/api"
SHIKI_UA = "MahiruBot/1.0 (github.com/xtekky/gpt4free consumer)"
JIKAN_BASE = "https://api.jikan.moe/v4"

def _strip_bbcode(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"\[/?[a-z0-9=_# ]+\]", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()

async def _shikimori_search(client: httpx.AsyncClient, title: str) -> dict | None:
    r = await client.get(
        SHIKI_BASE + "/animes",
        params={"search": title, "limit": 1},
        headers={"User-Agent": SHIKI_UA, "Accept": "application/json"},
    )
    r.raise_for_status()
    arr = r.json() or []
    return arr[0] if arr else None

async def _shikimori_full(client: httpx.AsyncClient, anime_id: int) -> dict:
    r = await client.get(
        f"{SHIKI_BASE}/animes/{anime_id}",
        headers={"User-Agent": SHIKI_UA, "Accept": "application/json"},
    )
    r.raise_for_status()
    return r.json()

async def _jikan_fallback(client: httpx.AsyncClient, title: str) -> dict | None:
    r = await client.get(f"{JIKAN_BASE}/anime",
                         params={"q": title, "limit": 1})
    r.raise_for_status()
    items = r.json().get("data", [])
    if not items:
        return None
    a = items[0]
    return {
        "title":     a.get("title"),
        "russian":   None,
        "score":     a.get("score"),
        "episodes":  a.get("episodes"),
        "status":    a.get("status"),
        "aired":     (a.get("aired") or {}).get("string"),
        "genres":    [g["name"] for g in a.get("genres", [])],
        "description": (a.get("synopsis") or "")[:800],
        "image":     (a.get("images", {}).get("jpg") or {}).get("image_url"),
        "url":       a.get("url"),
        "source":    "jikan",
    }

class AnimeInfoTool(Tool):
    name = "anime_info"
    description = (
        "Получить дополнительную информацию об аниме (рейтинг, эпизоды, статус, год) через "
        "Shikimori. Вызывай ТОЛЬКО если пользователь специально спрашивает оценку/кол-во серий/"
        "статус. Про сюжет популярного аниме отвечай сама без вызова."
    )
    parameters = {
        "type": "object",
        "properties": {"title": {"type": "string",
                                   "description": "Название (русское или латиница)"}},
        "required": ["title"],
    }

    async def run(self, args, *, session, user_id: int):
        title = (args.get("title") or "").strip()
        if not title:
            return {"error": "no title"}

        ck = f"shiki:info:{title.lower()}"
        cached = await cache_get(ck)
        if cached:
            return cached

        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            try:
                found = await _shikimori_search(c, title)
                if found:
                    full = await _shikimori_full(c, found["id"])
                    image = ((full.get("image") or {}).get("original")
                             or (full.get("image") or {}).get("preview"))
                    if image and image.startswith("/"):
                        image = "https://shikimori.one" + image
                    out = {
                        "title":     full.get("russian") or full.get("name"),
                        "title_original": full.get("name"),
                        "score":     full.get("score"),
                        "episodes":  full.get("episodes") or full.get("episodes_aired"),
                        "kind":      full.get("kind"),
                        "status":    full.get("status"),
                        "aired":     full.get("aired_on"),
                        "released":  full.get("released_on"),
                        "genres":    [(g.get("russian") or g.get("name"))
                                       for g in (full.get("genres") or [])],
                        "description": _strip_bbcode(full.get("description"))[:800],
                        "image":     image,
                        "url":       "https://shikimori.one/animes/" + str(full["id"]),
                        "source":    "shikimori",
                    }
                    await cache_set(ck, out, ttl=3600)
                    return out
            except Exception as e:
                shiki_err = f"{type(e).__name__}: {e}"
            else:
                shiki_err = "not found"

            try:
                out = await _jikan_fallback(c, title)
                if out:
                    await cache_set(ck, out, ttl=3600)
                    return out
            except Exception as e:
                return {
                    "error": "api unavailable",
                    "shikimori": shiki_err,
                    "jikan": f"{type(e).__name__}: {e}",
                    "hint": "Ответь пользователю по своей памяти, не выдумывая цифры.",
                }

        return {"error": "not found", "query": title,
                "hint": "Ответь по своей памяти, если знаешь это аниме."}

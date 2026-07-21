"""Инструмент: веб-поиск."""
from __future__ import annotations
import re
import html
import httpx

from methods.base import Tool
from utils.cache import cache_get, cache_set
from utils.logger import log

DDG_HTML = "https://html.duckduckgo.com/html/"
DDG_LITE = "https://lite.duckduckgo.com/lite/"
WIKI_RU = "https://ru.wikipedia.org/w/api.php"
WIKI_EN = "https://en.wikipedia.org/w/api.php"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")

_LINK_RE = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")

def _clean(s: str) -> str:
    return html.unescape(_TAG_RE.sub("", s)).strip()

def _unwrap_ddg_url(u: str) -> str:
    m = re.search(r"uddg=([^&]+)", u)
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1))
    if u.startswith("//"):
        return "https:" + u
    return u

async def _ddg_html(query: str, num: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                 headers={"User-Agent": UA}) as c:
        r = await c.post(DDG_HTML, data={"q": query, "kl": "ru-ru"})
        r.raise_for_status()
        body = r.text

    links = _LINK_RE.findall(body)
    snippets = _SNIPPET_RE.findall(body)
    out: list[dict] = []
    for i, (url, title_html) in enumerate(links[:num]):
        url = _unwrap_ddg_url(url)
        snip = _clean(snippets[i]) if i < len(snippets) else ""
        out.append({"title": _clean(title_html), "link": url, "snippet": snip[:300]})
    return out

async def _ddg_search_lib(query: str, num: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
    except Exception:
        return []
    try:
        with DDGS(headers={"User-Agent": UA}) as d:
            results = list(d.text(query, region="ru-ru", safesearch="moderate",
                                  max_results=num)) or []
        return [{"title": r.get("title"), "link": r.get("href"),
                 "snippet": (r.get("body") or "")[:300]}
                for r in results]
    except Exception:
        return []

async def _wiki(query: str, num: int) -> list[dict]:
    async def _one(base: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": UA}) as c:
            r = await c.get(base, params={
                "action": "opensearch", "search": query,
                "limit": num, "namespace": 0, "format": "json",
            })
            r.raise_for_status()
            data = r.json()
        _, titles, descs, urls = data
        return [{"title": t, "link": u, "snippet": d[:300]}
                for t, d, u in zip(titles, descs, urls)]

    try:
        out = await _one(WIKI_RU)
        if out:
            return out
    except Exception:
        pass
    try:
        return await _one(WIKI_EN)
    except Exception:
        return []

class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Бесплатный поиск в интернете (DuckDuckGo, без ключа). Используй когда нужны "
        "актуальные факты, новости, цены, игры, манга/аниме обзоры, инструкции. "
        "Не вызывай для банальных вещей, которые ты знаешь."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "num":   {"type": "integer", "minimum": 1, "maximum": 8, "default": 5},
        },
        "required": ["query"],
    }

    async def run(self, args, *, session, user_id: int):
        q = (args.get("query") or "").strip()
        if not q:
            return {"results": []}
        num = int(args.get("num") or 5)
        ck = f"web:{q}:{num}"
        cached = await cache_get(ck)
        if cached:
            return cached

        results: list[dict] = []
        try:
            results = await _ddg_html(q, num)
        except Exception as e:
            log.debug(f"web_search: DDG html failed: {e}")

        if not results:
            results = await _ddg_search_lib(q, num)

        if not results:
            results = await _wiki(q, num)

        if not results:
            return {"query": q, "results": [], "hint": "Не удалось найти — ответь по своей памяти."}

        out = {"query": q, "results": results}
        await cache_set(ck, out, ttl=600)
        return out

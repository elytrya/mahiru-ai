"""Инструмент: поиск игр в Steam."""
from __future__ import annotations
import re
import httpx

from methods.base import Tool
from utils.cache import cache_get, cache_set

STORE_SEARCH = "https://store.steampowered.com/api/storesearch/"
APP_DETAILS = "https://store.steampowered.com/api/appdetails"
APP_PAGE = "https://store.steampowered.com/app/"
APP_REVIEWS = "https://store.steampowered.com/appreviews/"

_TAG_RE = re.compile(r"<[^>]+>")

def _strip_html(s: str | None) -> str:
    if not s:
        return ""
    return _TAG_RE.sub("", s).strip()

def _price_vibe(game: dict) -> str:
    if game.get("is_free"):
        return "игра бесплатная — можно смело советовать 'гони качай, оно же free'"
    if game.get("coming_soon"):
        return "игра ещё не вышла — можно поворчать 'ждём-с'"
    price = game.get("price")
    disc = game.get("discount") or 0
    cur = game.get("currency") or ""
    if price is None:
        return "цена непонятна — можно пошутить что ценник где-то затерялся"
    parts = []
    if disc and disc > 0:
        parts.append(f"скидка -{disc}% — повод обрадоваться и подтолкнуть взять")
    try:
        p = float(price)
    except Exception:
        p = None
    if p is not None:
        if cur in ("RUB", "₽") or cur == "RUB":
            if p >= 3000:
                parts.append("дороговато, кусается")
            elif p <= 500:
                parts.append("совсем недорого, можно брать не думая")
            else:
                parts.append("цена норм, в пределах разумного")
        else:
            if p >= 50:
                parts.append("дороговато")
            elif p <= 10:
                parts.append("совсем дёшево")
            else:
                parts.append("цена ок")
    return "; ".join(parts) or "цена обычная"

async def steam_store_search(q: str, cc: str = "ru") -> list[dict]:
    q = (q or "").strip()
    if not q:
        return []
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(STORE_SEARCH, params={"term": q, "l": "russian", "cc": cc})
        r.raise_for_status()
        data = r.json()
    items: list[dict] = []
    for it in (data.get("items") or [])[:8]:
        price = it.get("price") or {}
        items.append({
            "appid":    it.get("id"),
            "title":    it.get("name"),
            "price":    (price.get("final", 0) / 100 if price else None),
            "currency": price.get("currency") if price else None,
            "cover":    it.get("tiny_image"),
            "url":      APP_PAGE + str(it.get("id", "")),
        })
    return items

class SteamSearchTool(Tool):
    name = "steam_search"
    description = (
        "Найти игры в Steam по названию. Возвращает список: appid, название, цена, ссылка. "
        "Используй когда парень спрашивает про игру в Стиме (там ли, сколько стоит, есть ли)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "cc":    {"type": "string", "default": "ru", "description": "Страна для цены (ru/us/kz и т.д.)"},
        },
        "required": ["query"],
    }

    async def run(self, args, *, session, user_id: int):
        q = (args.get("query") or "").strip()
        cc = (args.get("cc") or "ru").lower()
        if not q:
            return {"results": []}
        ck = f"steam:search:{q}:{cc}"
        cached = await cache_get(ck)
        if cached:
            return cached

        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(STORE_SEARCH, params={"term": q, "l": "russian", "cc": cc})
            r.raise_for_status()
            data = r.json()

        items = []
        for it in (data.get("items") or [])[:8]:
            price = it.get("price") or {}
            items.append({
                "appid":    it.get("id"),
                "title":    it.get("name"),
                "price":    (price.get("final", 0) / 100 if price else None),
                "currency": price.get("currency") if price else None,
                "platforms": it.get("platforms", {}),
                "cover":    it.get("tiny_image"),
                "url":      APP_PAGE + str(it.get("id", "")),
            })
        out = {"query": q, "results": items}
        await cache_set(ck, out, ttl=1800)
        return out

class SteamGameTool(Tool):
    name = "steam_game"
    description = (
        "Подробности об игре Steam по appid: описание, жанры, компания, дата выхода, цена. "
        "Вызывай после steam_search, когда выбрала конкретную игру."
    )
    parameters = {
        "type": "object",
        "properties": {
            "appid": {"type": "integer"},
            "cc":    {"type": "string", "default": "ru"},
        },
        "required": ["appid"],
    }

    async def run(self, args, *, session, user_id: int):
        appid = args.get("appid")
        if not appid:
            return {"error": "no appid"}
        cc = (args.get("cc") or "ru").lower()
        ck = f"steam:game:{appid}:{cc}"
        cached = await cache_get(ck)
        if cached:
            return cached

        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(APP_DETAILS, params={"appids": appid, "l": "russian", "cc": cc})
            r.raise_for_status()
            payload = r.json() or {}

        node = payload.get(str(appid)) or {}
        if not node.get("success"):
            return {"error": "игра не найдена"}
        d = node.get("data") or {}
        price = d.get("price_overview") or {}
        game = {
            "appid":     d.get("steam_appid"),
            "title":     d.get("name"),
            "type":      d.get("type"),
            "short":     _strip_html(d.get("short_description"))[:500],
            "about":     _strip_html(d.get("about_the_game"))[:800],
            "developers": d.get("developers") or [],
            "publishers": d.get("publishers") or [],
            "genres":    [g.get("description") for g in (d.get("genres") or [])],
            "categories": [c.get("description") for c in (d.get("categories") or [])],
            "release":   (d.get("release_date") or {}).get("date"),
            "coming_soon": (d.get("release_date") or {}).get("coming_soon"),
            "is_free":   d.get("is_free"),
            "price":     (price.get("final", 0) / 100) if price else None,
            "discount":  price.get("discount_percent") if price else None,
            "currency":  price.get("currency") if price else None,
            "platforms": d.get("platforms"),
            "cover":     d.get("header_image"),
            "url":       APP_PAGE + str(d.get("steam_appid", appid)),
        }
        game["price_vibe"] = _price_vibe(game)
        out = {
            "game": game,
            "_send_photo": game["cover"],
            "caption": f"{game['title']} — {game['url']}",
            "_hint": (
                "НЕ пересказывай всю карточку. Скажи живую реакцию в 1–2 фразы, обязательно отреагируй на цену (price_vibe). "
                "Если уместно — вызови steam_reviews и принеси угарный отзыв."
            ),
        }
        await cache_set(ck, out, ttl=3600)
        return out

def _score_desc(summary: dict) -> str:
    total = summary.get("total_reviews") or 0
    pos = summary.get("total_positive") or 0
    if not total:
        return "отзывов пока мало"
    pct = round(pos / total * 100)
    if pct >= 90:
        vibe = "люди в восторге"
    elif pct >= 75:
        vibe = "в целом хвалят"
    elif pct >= 55:
        vibe = "мнения смешанные"
    elif pct >= 40:
        vibe = "больше ругают"
    else:
        vibe = "разносят в пух и прах"
    return f"{pct}% положительных из {total} — {vibe}"

class SteamReviewsTool(Tool):
    name = "steam_reviews"
    description = (
        "Отзывы об игре Steam по appid: общая оценка (% положительных) и самые УГАРНЫЕ/смешные отзывы "
        "(по кол-ву лайков 'смешно'), а также пару полезных. Вызывай когда надо заглянуть в отзывы — "
        "например найти что-нибудь угарное чтобы посмеяться вместе, или понять стоит ли игра. Вызывай после steam_search."
    )
    parameters = {
        "type": "object",
        "properties": {
            "appid": {"type": "integer", "description": "appid из steam_search"},
            "query": {"type": "string",
                       "description": "название игры (если appid неизвестен — найду по имени сама)"},
            "lang":  {"type": "string", "default": "russian",
                       "description": "язык отзывов: russian / english / all"},
            "funny": {"type": "boolean", "default": True,
                       "description": "если true — сортировать по 'смешно' и вернуть угарные"},
        },
        "required": [],
    }

    async def run(self, args, *, session, user_id: int):
        appid = args.get("appid")
        if not appid and args.get("query"):
            found = await steam_store_search(str(args["query"]))
            if found:
                appid = found[0]["appid"]
        if not appid:
            return {"error": "no appid", "hint": "укажи appid или query (название игры)"}
        lang = (args.get("lang") or "russian").lower()
        want_funny = args.get("funny", True)
        ck = f"steam:reviews:{appid}:{lang}"
        cached = await cache_get(ck)
        if cached:
            return cached

        params = {
            "json": 1,
            "filter": "all",
            "language": lang,
            "review_type": "all",
            "purchase_type": "all",
            "num_per_page": 100,
            "filter_offtopic_activity": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(APP_REVIEWS + str(appid), params=params)
                r.raise_for_status()
                data = r.json() or {}
        except Exception as e:
            return {"error": f"не смогла взять отзывы: {e}",
                    "hint": "Ответь по-человечески без отзывов."}

        if data.get("success") != 1:
            return {"error": "Steam не отдал отзывы"}

        summary = data.get("query_summary") or {}
        raw = data.get("reviews") or []

        def _clean(rev: dict) -> dict:
            txt = _strip_html(rev.get("review") or "").strip()
            return {
                "text": txt[:400],
                "voted_up": rev.get("voted_up"),
                "votes_up": rev.get("votes_up") or 0,
                "votes_funny": rev.get("votes_funny") or 0,
                "playtime_h": round((((rev.get("author") or {}).get("playtime_forever") or 0) / 60), 1),
            }

        cleaned = [_clean(x) for x in raw if isinstance(x, dict)]
        cleaned = [c for c in cleaned if len(c["text"]) >= 12]

        funny = sorted(cleaned, key=lambda x: x["votes_funny"], reverse=True)
        funny = [c for c in funny if c["votes_funny"] > 0][:3]
        helpful = sorted(cleaned, key=lambda x: x["votes_up"], reverse=True)[:3]

        out = {
            "appid": appid,
            "summary": _score_desc(summary),
            "review_word": summary.get("review_score_desc"),
            "funny_reviews": funny if want_funny else [],
            "helpful_reviews": helpful,
            "_hint": (
                "НЕ вываливай список отзывов. Выбери 1 самый угарный/меткий, перескажи его своими словами или коротко процитируй, "
                "посмейся и свяжи с общей оценкой. Поддержи диалог, а не просто отчитайся."
            ),
        }
        await cache_set(ck, out, ttl=1800)
        return out

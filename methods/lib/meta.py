from __future__ import annotations
from typing import Any

from methods.lib.client import api_get, LibError
from utils.logger import log

_META_FIELDS = [
    "background", "eng_name", "otherNames", "summary", "releaseDate",
    "type_id", "caution", "views", "rate_avg", "rate", "genres", "tags",
    "teams", "franchise", "authors", "publisher", "moderated", "metadata",
    "chap_count", "status_id", "artists", "format",
]

def _pm_text(node: Any) -> str:
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    if t == "text":
        return node.get("text", "") or ""
    if t == "hardBreak":
        return "\n"
    inner = "".join(_pm_text(c) for c in (node.get("content") or []))
    if t in ("paragraph", "heading", "blockquote"):
        return inner + "\n\n"
    return inner

def extract_summary(summary: Any) -> str:
    if isinstance(summary, str):
        return summary.strip()
    if isinstance(summary, dict):
        return _pm_text(summary).strip()
    return ""

def _names(items: Any) -> list[str]:
    out: list[str] = []
    for it in (items or []):
        if isinstance(it, dict):
            nm = it.get("rus_name") or it.get("name")
            if nm:
                out.append(str(nm))
    return out

def _cover_url(cover: Any) -> str | None:
    if isinstance(cover, dict):
        return cover.get("default") or cover.get("md") or cover.get("thumbnail")
    return None

async def fetch_title_meta(kind: str, slug: str) -> dict[str, Any]:
    info = await api_get(kind, f"/api/manga/{slug}", params={"fields[]": _META_FIELDS})
    d = info.get("data") if isinstance(info, dict) else None
    if not isinstance(d, dict):
        raise LibError("пустой ответ метаданных")

    rating = d.get("rating") if isinstance(d.get("rating"), dict) else {}
    views = d.get("views") if isinstance(d.get("views"), dict) else {}
    return {
        "id": d.get("id"),
        "slug": d.get("slug_url") or slug,
        "name": d.get("rus_name") or d.get("name") or slug,
        "orig_name": d.get("name") or "",
        "eng_name": d.get("eng_name") or "",
        "other_names": [str(x) for x in (d.get("otherNames") or []) if x],
        "summary": extract_summary(d.get("summary")),
        "year": (str(d.get("releaseDate")).strip() or None) if d.get("releaseDate") else None,
        "status": (d.get("status") or {}).get("label") if isinstance(d.get("status"), dict) else None,
        "type": (d.get("type") or {}).get("label") if isinstance(d.get("type"), dict) else None,
        "age": (d.get("ageRestriction") or {}).get("label") if isinstance(d.get("ageRestriction"), dict) else None,
        "rating": rating.get("average"),
        "votes": rating.get("votes"),
        "views": views.get("formated") or views.get("short"),
        "genres": [g.get("name") for g in (d.get("genres") or []) if isinstance(g, dict) and g.get("name")],
        "tags": [g.get("name") for g in (d.get("tags") or []) if isinstance(g, dict) and g.get("name")],
        "authors": _names(d.get("authors")),
        "artists": _names(d.get("artists")),
        "publisher": _names(d.get("publisher")),
        "teams": _names(d.get("teams")),
        "cover": _cover_url(d.get("cover")),
    }

async def fetch_covers(kind: str, slug: str, limit: int = 10) -> list[str]:
    try:
        data = await api_get(kind, f"/api/manga/{slug}/covers")
    except LibError as e:
        log.debug(f"covers fetch failed: {e}")
        return []
    arr = data.get("data") if isinstance(data, dict) else None
    urls: list[str] = []
    if isinstance(arr, list):
        for c in arr:
            if not isinstance(c, dict):
                continue
            u = _cover_url(c.get("cover"))
            if u:
                urls.append(u)
    return urls[:limit]

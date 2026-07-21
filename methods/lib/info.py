"""Инструмент: информация о тайтле *Lib."""
from __future__ import annotations
from typing import Any

from methods.base import Tool
from methods.lib.client import api_get, LibError
from utils.cache import cache_get, cache_set
from utils.logger import log

_KINDS = {"manga", "ranobe", "hentai"}

class LibInfoTool(Tool):
    name = "lib_info"
    description = (
        "Детали тайтла (описание, год, жанры) + список глав с номерами. "
        "Служит чтобы выбрать какие главы скачать в lib_download."
    )
    parameters = {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "slug_url тайтла из lib_search"},
            "kind": {
                "type": "string",
                "enum": ["manga", "ranobe", "hentai"],
                "default": "manga",
            },
            "chapters_preview": {
                "type": "integer",
                "description": "сколько первых+последних глав вернуть (чтобы не раздувать ответ)",
                "default": 10,
            },
        },
        "required": ["slug"],
    }

    async def run(self, args: dict[str, Any], *, session=None, user_id: int = 0) -> dict[str, Any]:
        slug = str(args.get("slug") or "").strip()
        kind = str(args.get("kind") or "manga").lower()
        chapters_preview = args.get("chapters_preview", 10)
        if kind not in _KINDS:
            return {"error": f"kind должен быть manga/ranobe/hentai"}
        if not slug:
            return {"error": "slug пуст"}

        ck = f"libinfo:{kind}:{slug}"
        cached = await cache_get(ck)
        if cached is not None:
            return cached

        try:
            info = await api_get(kind, f"/api/manga/{slug}", params={
                "fields[]": [
                    "eng_name", "otherNames", "summary", "releaseDate",
                    "type_id", "caution", "views", "close_view",
                    "rate_avg", "rate", "genres", "tags",
                    "teams", "franchise", "authors", "publisher",
                    "chap_count", "status_id", "artists", "format",
                ],
            })
        except LibError as e:
            return {"error": str(e)}

        try:
            chapters = await api_get(kind, f"/api/manga/{slug}/chapters")
        except LibError as e:
            return {"error": f"не смогла взять список глав: {e}"}

        d = info.get("data") if isinstance(info, dict) else None
        if not isinstance(d, dict):
            return {"error": "пустой ответ API"}

        chs = chapters.get("data") if isinstance(chapters, dict) else None
        if not isinstance(chs, list):
            chs = []

        chap_list: list[dict[str, Any]] = []
        for c in chs:
            if not isinstance(c, dict):
                continue
            chap_list.append({
                "volume": c.get("volume"),
                "number": c.get("number"),
                "name": c.get("name") or "",
                "id": c.get("id"),
            })

        total = len(chap_list)
        preview_n = max(1, int(chapters_preview or 10))
        if total <= preview_n * 2:
            preview = chap_list
        else:
            preview = chap_list[:preview_n] + [{"...": f"({total - preview_n * 2} глав пропущено)"}] + chap_list[-preview_n:]

        result = {
            "kind": kind,
            "slug": slug,
            "name": d.get("rus_name") or d.get("name"),
            "eng_name": d.get("eng_name"),
            "summary": d.get("summary"),
            "year": d.get("releaseDate") or d.get("releaseDateString"),
            "status": (d.get("status") or {}).get("label") if isinstance(d.get("status"), dict) else None,
            "type": (d.get("type") or {}).get("label") if isinstance(d.get("type"), dict) else None,
            "rating": (d.get("rating") or {}).get("average") if isinstance(d.get("rating"), dict) else d.get("rate_avg"),
            "genres": [g.get("name") for g in (d.get("genres") or []) if isinstance(g, dict)],
            "tags":   [g.get("name") for g in (d.get("tags") or []) if isinstance(g, dict)],
            "chapters_total": total,
            "chapters_preview": preview,
            "_hint": (
                "чтобы скачать — вызови lib_download(slug, kind, chapter_from, chapter_to). "
                "chapter_from/to — номера глав ака number."
            ),
        }
        await cache_set(ck, result, ttl=600)
        return result

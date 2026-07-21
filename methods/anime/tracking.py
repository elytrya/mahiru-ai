"""Инструмент: отслеживание просмотренного аниме."""
from __future__ import annotations
from sqlalchemy import select

from methods.base import Tool
from db.models import AnimeHistory

class AnimeTrackingTool(Tool):
    name = "anime_tracking"
    description = (
        "Сохранить/показать список аниме пользователя. action=add добавляет, action=list выводит."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "list"]},
            "title":  {"type": "string"},
            "status": {"type": "string",
                       "enum": ["watching", "completed", "planned", "dropped"]},
            "score":  {"type": "number"},
            "shikimori_id": {"type": "integer"},
        },
        "required": ["action"],
    }

    async def run(self, args, *, session, user_id: int):
        action = args["action"]
        if action == "list":
            res = await session.execute(select(AnimeHistory)
                                        .where(AnimeHistory.user_id == user_id))
            items = [{"title": a.title, "status": a.status, "score": a.score}
                     for a in res.scalars().all()]
            return {"items": items}
        if action == "add":
            entry = AnimeHistory(
                user_id=user_id,
                anilist_id=args.get("shikimori_id"),
                title=args.get("title", "?"),
                status=args.get("status", "watching"),
                score=args.get("score"),
            )
            session.add(entry)
            await session.commit()
            return {"ok": True}
        return {"error": "unknown action"}

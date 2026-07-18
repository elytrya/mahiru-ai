from __future__ import annotations
from methods.base import Tool
from memory.storage import save

class MemorySaveTool(Tool):
    name = "memory_save"
    description = (
        "Сохранить важный факт о пользователе в долгосрочную память. "
        "Используй только для действительно важной информации (importance >= 60)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "fact": {"type": "string"},
            "category": {"type": "string",
                         "enum": ["preference", "fact", "event", "emotion", "relationship"]},
            "importance": {"type": "integer", "minimum": 0, "maximum": 100},
        },
        "required": ["fact", "category", "importance"],
    }

    async def run(self, args, *, session, user_id: int):
        if int(args["importance"]) < 60:
            return {"skipped": True}
        await save(session, user_id, args["fact"], args["category"],
                   int(args["importance"]), source="llm")
        return {"ok": True}

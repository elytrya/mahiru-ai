from __future__ import annotations
from methods.base import Tool

class ImageVisionTool(Tool):
    name = "image_vision"
    description = (
        "Проанализировать изображение, которое прислал пользователь (напр. страница манги): "
        "распознать текст, описать сцену, перевести, объяснить происходящее. "
        "Само изображение уже прикреплено к контексту vision-модели."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {"type": "string",
                     "description": "'ocr' | 'describe' | 'translate' | 'explain'"},
            "target_lang": {"type": "string", "default": "ru"},
        },
        "required": ["task"],
    }

    async def run(self, args, *, session, user_id: int):
        task = args.get("task", "describe")
        lang = args.get("target_lang", "ru")
        return {
            "instruction": f"perform task={task} lang={lang} на прикреплённом изображении",
        }

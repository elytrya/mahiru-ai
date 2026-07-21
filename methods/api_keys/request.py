"""Инструмент: запросить у пользователя нужный API-ключ."""
from __future__ import annotations
from methods.base import Tool

KEY_HINTS = {
    "google":        ("GOOGLE_API_KEY", "GOOGLE_CX",
                      "https://developers.google.com/custom-search/v1/introduction"),
    "mangalib":      ("MANGALIB_TOKEN", None,
                      "https://mangalib.me — вытащи Bearer-токен из DevTools"),
    "hentailib":     ("HENTAILIB_TOKEN", None, "то же что mangalib"),
    "ranobelib":     ("RANOBELIB_TOKEN", None, "то же что mangalib"),
    "steam":         ("STEAM_API_KEY", None,
                      "https://steamcommunity.com/dev/apikey — нужен только для библиотеки пользователя"),
    "gemini":        ("GEMINI_API_KEY", None, "https://aistudio.google.com/apikey"),
    "openai":        ("OPENAI_API_KEY", None, "https://platform.openai.com/api-keys"),
    "claude":        ("ANTHROPIC_API_KEY", None, "https://console.anthropic.com/"),
    "deepseek":      ("DEEPSEEK_API_KEY", None, "https://platform.deepseek.com/api_keys"),
}

class RequestApiKeyTool(Tool):
    name = "request_api_key"
    description = (
        "Попросить у пользователя API-ключ, если его не хватает (напр. google, mangalib, steam). "
        "Вызывай когда другой тул вернул ошибку про отсутствующий ключ или когда парень сам просит "
        "подключить сервис. Вернет пользователю инструкцию как ввести ключ через /setkey."
    )
    parameters = {
        "type": "object",
        "properties": {
            "service": {"type": "string",
                        "description": "google | mangalib | hentailib | ranobelib | steam | gemini | openai | claude | deepseek"},
            "reason":  {"type": "string", "description": "Зачем нужен ключ (коротко)"},
        },
        "required": ["service"],
    }

    async def run(self, args, *, session, user_id: int):
        service = (args.get("service") or "").strip().lower()
        reason = (args.get("reason") or "").strip() or "нужен для работы"
        info = KEY_HINTS.get(service)
        if not info:
            return {"error": f"неизвестный сервис {service!r}",
                    "available": list(KEY_HINTS.keys())}
        key_name, extra_name, url = info
        lines = [
            f"🔐 Нужен ключ для <b>{service}</b>: {reason}",
            "",
            f"Где взять: {url}",
            "",
            "Введи в чат:",
            f"<code>/setkey {key_name} ТВОЙ_КЛЮЧ</code>",
        ]
        if extra_name:
            lines.append(f"<code>/setkey {extra_name} ТВОЙ_CX</code>")
        text = "\n".join(lines)
        return {"requested": service, "key_name": key_name, "_send_message": text}

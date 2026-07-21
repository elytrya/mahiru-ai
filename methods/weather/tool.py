"""Инструмент погоды: Махиру может узнать реальную погоду в любом городе.

Использует utils.weather.get_weather (OpenWeather). Зови когда он спрашивает
'какая погода в <город>', 'холодно ли сейчас в ...', 'дождь у меня?',
или когда сама хочешь заботливо проверить погоду у него или в своём городе.
"""
from __future__ import annotations

from methods.base import Tool
from utils.weather import get_weather, format_weather
from config import settings
from utils.cache import cache_get, cache_set
from utils.logger import log


class WeatherTool(Tool):
    name = "weather"
    description = (
        "Узнать РЕАЛЬНУЮ текущую погоду в конкретном городе (OpenWeather). "
        "Зови когда он спрашивает про погоду где-то ('какая погода в Питере', "
        "'холодно сейчас в Москве?', 'дождь у меня?'), или когда сама хочешь "
        "заботливо глянуть погоду у него или у себя. "
        "city - название города; пусто = город владельца; 'self'/'у меня' = твой город."
    )
    parameters = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": (
                    "Город, напр. 'Москва', 'Tokyo', 'London'. "
                    "Пусто = город владельца. 'self' = твой (Махиру) город."
                ),
            },
        },
        "required": [],
    }

    async def run(self, args, *, session, user_id: int):
        raw = (args.get("city") or "").strip()
        low = raw.lower()
        if low in ("self", "я", "у меня", "мой", "свой", "мой город", "дома"):
            city = (getattr(settings, "MAHIRU_CITY", "") or "").strip() or None
        else:
            city = raw or None

        ck = f"weather_tool:{(city or 'owner').lower()}"
        cached = await cache_get(ck)
        if cached:
            return cached

        w = await get_weather(city)
        if not w:
            return {
                "error": "no_weather",
                "hint": (
                    "нет ключа OpenWeather или город не найден - ответь по-человечески "
                    "без точных цифр, не показывай техничку"
                ),
            }
        out = {
            "city": w.get("city"),
            "temp": w.get("temp"),
            "feels": w.get("feels"),
            "desc": w.get("desc"),
            "advice": w.get("advice"),
            "pretty": format_weather(w),
        }
        await cache_set(ck, out, ttl=600)
        log.info(f"\U0001f326 weather tool: {out.get('pretty')}")
        return out

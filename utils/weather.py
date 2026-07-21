"""Погода-забота через OpenWeather.

Махиру смотрит погоду в городе владельца и может позаботиться:
«там у тебя дождь, не забудь зонт». Ключ OpenWeather и город настраиваются
в setup_wizard / /weather / .env (OPENWEATHER_API_KEY, WEATHER_CITY).
"""
from __future__ import annotations

from config import settings
from utils.settings_kv import get_key
from utils.logger import log

_API_URL = "https://api.openweathermap.org/data/2.5/weather"

_RAIN = {"Rain", "Drizzle", "Thunderstorm"}
_SNOW = {"Snow"}


def _advice(main: str, temp: float | None) -> str:
    """Короткий совет-забота по погоде (без тире «-»)."""
    if main in _RAIN:
        return "на улице дождь, не забудь зонт"
    if main in _SNOW:
        return "идёт снег, одевайся теплее"
    if temp is not None:
        if temp <= -5:
            return "на улице мороз, кутайся потеплее"
        if temp <= 5:
            return "прохладно, оденься потеплее"
        if temp >= 30:
            return "жара, пей больше воды"
    return ""


async def get_weather(city: str | None = None) -> dict | None:
    """Возвращает dict с погодой или None (нет ключа/города/ошибка).

    Поля: city, desc, temp, feels, main, advice.
    """
    city = (city or getattr(settings, "WEATHER_CITY", "") or "").strip()
    if not city:
        return None
    api = await get_key("OPENWEATHER_API_KEY")
    if not api:
        return None

    params = {
        "q": city,
        "appid": api,
        "units": getattr(settings, "WEATHER_UNITS", "metric") or "metric",
        "lang": getattr(settings, "WEATHER_LANG", "ru") or "ru",
    }
    try:
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(_API_URL, params=params) as r:
                if r.status != 200:
                    log.warning(f"OpenWeather {r.status} для города {city!r}")
                    return None
                data = await r.json()
    except Exception:
        log.exception("OpenWeather запрос упал")
        return None

    try:
        w0 = (data.get("weather") or [{}])[0]
        main = w0.get("main", "")
        desc = w0.get("description", "") or main
        m = data.get("main") or {}
        temp = m.get("temp")
        feels = m.get("feels_like")
        name = data.get("name") or city
    except Exception:
        log.exception("OpenWeather разбор ответа упал")
        return None

    return {
        "city": name,
        "desc": desc,
        "temp": temp,
        "feels": feels,
        "main": main,
        "advice": _advice(main, temp),
    }


def format_weather(w: dict) -> str:
    """Короткая строка для показа в /weather (без тире)."""
    if not w:
        return "погода недоступна"
    t = w.get("temp")
    parts = [w.get("city", "")]
    if t is not None:
        parts.append(f"{round(t)}°")
    if w.get("desc"):
        parts.append(str(w["desc"]))
    line = ", ".join(str(x) for x in parts if x)
    if w.get("advice"):
        line += f" ({w['advice']})"
    return line

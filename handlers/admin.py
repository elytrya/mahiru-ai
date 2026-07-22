"""Админ-команды и настройка поведения бота (/admin и т.п.)."""
from __future__ import annotations
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import settings
from db.session import SessionLocal
from db import repo
from utils.settings_kv import BEHAVIOR_FIELDS, set_behavior, set_key, get_key

router = Router(name="admin")

def is_admin(uid: int) -> bool:
    return uid in settings.admin_ids

def admin_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🌸 Личность",     callback_data="adm:personality"),
         InlineKeyboardButton(text="🧠 Память",       callback_data="adm:memory")],
        [InlineKeyboardButton(text="⚙️ AI настройки", callback_data="adm:ai"),
         InlineKeyboardButton(text="🔌 Провайдер",     callback_data="adm:provider")],
        [InlineKeyboardButton(text="🔐 API ключи",   callback_data="adm:keys"),
         InlineKeyboardButton(text="📊 Статистика",   callback_data="adm:stats")],
        [InlineKeyboardButton(text="🎭 Человечность", callback_data="adm:human")],
        [InlineKeyboardButton(text="🧹 Очистка",     callback_data="adm:clear"),
         InlineKeyboardButton(text="📦 Импорт/Экспорт",
                              callback_data="adm:io")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

@router.message(Command("admin"))
async def admin_cmd(msg: Message):
    if not is_admin(msg.from_user.id):
        return
    await msg.answer("Панель администратора:", reply_markup=admin_menu())


@router.message(Command("human"))
async def human_cmd(msg: Message):
    """Быстрый доступ к панели очеловечивания."""
    if not is_admin(msg.from_user.id):
        return
    from handlers.callbacks import render_human_panel
    text, kb = render_human_panel()
    await msg.answer(text, reply_markup=kb)


@router.message(Command("humanset"))
async def humanset_cmd(msg: Message):
    """Тонкая настройка: /humanset ПОЛЕ ЗНАЧЕНИЕ."""
    if not is_admin(msg.from_user.id):
        return
    parts = (msg.text or "").split(maxsplit=2)
    allowed = ", ".join(f.lower() for f in BEHAVIOR_FIELDS)
    if len(parts) < 3:
        await msg.answer(
            "Формат: <code>/humanset ПОЛЕ ЗНАЧЕНИЕ</code>\n\n"
            "Примеры:\n"
            "<code>/humanset typing_speed_cps 20</code>\n"
            "<code>/humanset ignore_chance 0.2</code>\n"
            "<code>/humanset no_emdash on</code>\n"
            "<code>/humanset split_messages off</code>\n\n"
            f"Доступные поля:\n<code>{allowed}</code>",
        )
        return
    field, value = parts[1], parts[2].strip()
    if field.upper() not in BEHAVIOR_FIELDS:
        await msg.answer(f"Нет такого поля. Доступные:\n<code>{allowed}</code>")
        return
    await set_behavior(field, value)
    new_val = getattr(settings, field.upper(), value)
    await msg.answer(f"Ок, <b>{field.upper()}</b> = <b>{new_val}</b> ✅")


@router.message(Command("weather"))
async def weather_cmd(msg: Message):
    """Погода-забота (OpenWeather): город, ключ, час, вкл/выкл, тест."""
    if not is_admin(msg.from_user.id):
        return
    from utils.weather import get_weather, format_weather
    parts = (msg.text or "").split(maxsplit=2)
    sub = parts[1].lower() if len(parts) > 1 else ""
    arg = parts[2].strip() if len(parts) > 2 else ""

    if sub in ("city", "город") and arg:
        await set_behavior("WEATHER_CITY", arg)
        await msg.answer(f"Ок, город для погоды: <b>{arg}</b> ✅")
        return
    if sub == "key" and arg:
        await set_key("OPENWEATHER_API_KEY", arg)
        await msg.answer("Ок, ключ OpenWeather сохранён ✅")
        return
    if sub in ("on", "off", "вкл", "выкл"):
        await set_behavior("WEATHER_ENABLED", "on" if sub in ("on", "вкл") else "off")
        state = "включена" if getattr(settings, "WEATHER_ENABLED", True) else "выключена"
        await msg.answer(f"Погода-забота теперь <b>{state}</b> ✅")
        return
    if sub == "test":
        w = await get_weather()
        if not w:
            await msg.answer("Не смогла получить погоду. Проверь ключ и город: <code>/weather key ...</code>, <code>/weather city ...</code>")
            return
        await msg.answer("Сейчас: " + format_weather(w))
        return

    enabled = "да" if getattr(settings, "WEATHER_ENABLED", True) else "нет"
    city = getattr(settings, "WEATHER_CITY", "") or "(не задан)"
    has_key = "есть" if await get_key("OPENWEATHER_API_KEY") else "нет"
    w = await get_weather()
    now_line = ("\nСейчас: " + format_weather(w)) if w else ""
    await msg.answer(
        "🌤 <b>Погода-забота (OpenWeather)</b>\n"
        f"Включена: <b>{enabled}</b>\n"
        f"Город: <b>{city}</b>\n"
        f"Ключ API: <b>{has_key}</b>\n"
        "Про погоду она вспоминает <b>сама, когда захочет</b> (без часов и расписания)"
        + now_line +
        "\n\nКоманды:\n"
        "<code>/weather city Москва</code> - город\n"
        "<code>/weather key &lt;APIKEY&gt;</code> - ключ OpenWeather\n"
        "<code>/weather on</code> / <code>/weather off</code>\n"
        "<code>/weather test</code> - проверить сейчас"
    )


@router.message(Command("screen"))
async def screen_cmd(msg: Message):
    """Смотрит на экран: вкл/выкл, монитор, тест. Когда смотреть — решает САМА."""
    if not is_admin(msg.from_user.id):
        return
    parts = (msg.text or "").split(maxsplit=2)
    sub = parts[1].lower() if len(parts) > 1 else ""
    arg = parts[2].strip() if len(parts) > 2 else ""

    if sub in ("on", "off", "вкл", "выкл"):
        await set_behavior("SCREEN_WATCH_ENABLED", "on" if sub in ("on", "вкл") else "off")
        state = "включено" if getattr(settings, "SCREEN_WATCH_ENABLED", False) else "выключено"
        await msg.answer(f"Подглядывание за экраном теперь <b>{state}</b> ✅\nКогда смотреть — она решает сама, по контексту.")
        return
    if sub in ("monitor", "монитор", "экран") and arg:
        if arg.isdigit():
            await set_behavior("SCREEN_WATCH_MONITOR", arg)
            await msg.answer(f"Ок, буду снимать монитор <b>{arg}</b> (0 = все сразу) ✅")
            return
        await msg.answer("Формат: <code>/screen monitor 1</code> (0 = все, 1 = первый, 2 = второй...)")
        return
    if sub == "test":
        from utils.screen import capture_screen_jpeg
        from aiogram.types import BufferedInputFile
        shot = capture_screen_jpeg()
        if not shot:
            await msg.answer("Не смогла снять экран 😢 (нет граф. среды/прав или не установлен mss/Pillow). Проверь, что бот запущен на компьютере с монитором.")
            return
        await msg.answer_photo(BufferedInputFile(shot, filename="screen.jpg"), caption="Вот что я сейчас вижу 👀")
        return

    from utils.screen import screen_available
    enabled = "да" if getattr(settings, "SCREEN_WATCH_ENABLED", False) else "нет"
    mon = getattr(settings, "SCREEN_WATCH_MONITOR", 0)
    avail = "доступен" if screen_available() else "недоступен сейчас"
    await msg.answer(
        "👀 <b>Смотрит на экран</b>\n"
        f"Включено: <b>{enabled}</b>\n"
        f"Монитор: <b>{mon}</b> (0 = все сразу)\n"
        f"Экран сейчас: <b>{avail}</b>\n\n"
        "Махиру заглядывает на экран <b>сама, когда захочет</b> (по контексту, без часов и лимитов).\n"
        "Также ты можешь просто написать ей «глянь на экран» — и она посмотрит.\n"
        "Нужен AI-провайдер с поддержкой картинок (gemini, gpt-4o и т.п.).\n\n"
        "Команды:\n"
        "<code>/screen on</code> / <code>/screen off</code>\n"
        "<code>/screen monitor 1</code> - какой монитор снимать\n"
        "<code>/screen test</code> - снять экран сейчас"
    )


@router.message(Command("petname"))
async def petname_cmd(msg: Message):
    """Ласковое прозвище (пет-нейм): показать / задать / сбросить."""
    if not is_admin(msg.from_user.id):
        return
    parts = (msg.text or "").split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    async with SessionLocal() as s:
        user = await repo.upsert_user(
            s, msg.from_user.id,
            username=msg.from_user.username,
            first_name=msg.from_user.first_name,
        )
        if not arg:
            cur = getattr(user, "pet_name", None)
            close = int(getattr(user, "closeness", 0) or 0)
            if cur:
                await msg.answer(
                    f"💕 Махиру зовёт тебя: <b>{cur}</b>\nБлизость: <b>{close}</b> очк.\n\n"
                    "<code>/petname зайка</code> - задать своё\n<code>/petname clear</code> - сбросить (сама придумает заново)"
                )
            else:
                await msg.answer(
                    f"Пока прозвища нет (близость: <b>{close}</b> очк.). "
                    "Махиру придумает его сама, когда вы станете ближе.\n\n"
                    "<code>/petname зайка</code> - задать вручную"
                )
            return
        if arg.lower() in ("clear", "сброс", "сбросить", "none", "-"):
            await repo.set_pet_name(s, user.id, None)
            await repo.set_setting(s, f"petname_tried:{user.id}", "")
            await msg.answer("Ок, прозвище сброшено. Махиру придумает новое сама ✅")
            return
        name = arg.split()[0][:32]
        await repo.set_pet_name(s, user.id, name)
        await msg.answer(f"Ок, теперь Махиру зовёт тебя <b>{name}</b> 💕")

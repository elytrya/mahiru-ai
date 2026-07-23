"""Обработчики inline-кнопок (callback query)."""
from __future__ import annotations
import json

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func

from config import settings
from db.session import SessionLocal
from db import repo
from db.models import Memory, Message, User
from memory.storage import clear as memory_clear
from utils.settings_kv import get_key, set_behavior

router = Router(name="callbacks")

PERSONALITY_DEFAULTS = {
    "name":            "Mahiru",
    "age":             19,
    "style":           "естественный, живой, разговорный",
    "character":       "заботливая, спокойная, немного дерзкая",
    "favorite_topics": "аниме, манга, музыка, космос",
    "interests":       "романтические истории, sci-fi",
    "emotionality":    45,
    "humor":           55,
    "speech":          "коротко, одной строкой, эмодзи почти не ставит, вопросы редко",
    "relationship_":   "её парень",
    "description":     "Просто девушка, с которой можно поболтать по-человечески.",
}

MANAGED_KEYS = [
    ("GOOGLE_API_KEY", "Google Custom Search"),
    ("GOOGLE_CX",      "Google CX (search engine id)"),
    ("GEMINI_API_KEY", "Google Gemini"),
    ("OPENAI_API_KEY", "OpenAI"),
    ("ANTHROPIC_API_KEY", "Claude"),
    ("DEEPSEEK_API_KEY", "DeepSeek"),
    ("YANDEX_API_KEY",  "Yandex AI Studio API key"),
    ("YANDEX_FOLDER",   "Yandex folder id (b1g...)"),
    ("YANDEX_PROMPT_ID","Yandex AI Studio prompt id (опц)"),
    ("LIB_TOKEN",       "MangaLib/RanobeLib/HentaiLib токен (общий)"),
    ("STEAM_API_KEY",   "Steam Web API (опционально)"),
    ("OPENWEATHER_API_KEY", "OpenWeather (погода-забота)"),
]

def back_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="« Назад", callback_data="adm:home")
    ]])

def _is_admin(uid: int) -> bool:
    return uid in settings.admin_ids

def _mask(v: str | None) -> str:
    if not v:
        return "—"
    if len(v) <= 6:
        return "*" * len(v)
    return v[:3] + "…" + v[-3:]

@router.callback_query(F.data.startswith("tool:"))
async def tool_info(cb: CallbackQuery):
    from handlers.messages import TOOL_CACHE
    tid = cb.data.split(":", 1)[1]
    entry = TOOL_CACHE.get(tid)
    if not entry:
        await cb.answer("Нет данных (устарели).", show_alert=True)
        return
    name, args, _ = entry
    try:
        pretty = json.dumps(args, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pretty = str(args)
    txt = f"🔧 {name}\n\n{pretty}"
    await cb.answer(txt[:200], show_alert=True)

@router.callback_query(F.data.startswith("adm:"))
async def admin_cb(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return

    action = cb.data.split(":", 1)[1]

    async with SessionLocal() as s:
        if action == "home":
            from handlers.admin import admin_menu
            await cb.message.edit_text("Панель администратора:", reply_markup=admin_menu())

        elif action == "personality":
            p = await repo.get_personality(s)
            text = (
                f"<b>Личность</b>\n"
                f"Имя: {p.name}\n"
                f"Возраст: {p.age}\n"
                f"Характер: {p.character}\n"
                f"Стиль: {p.style}\n"
                f"Речь: {p.speech}\n"
                f"Интересы: {p.interests}\n"
                f"Любимые темы: {p.favorite_topics}\n"
                f"Отношения: {p.relationship_}\n"
                f"Эмоциональность: {p.emotionality}/100\n"
                f"Юмор: {p.humor}/100\n\n"
                "Чтобы обновить поле: отправь\n<code>/set &lt;field&gt; &lt;value&gt;</code>\n"
            )
            kb = [
                [InlineKeyboardButton(text="🔄 Сбросить к дефолту",
                                      callback_data="adm:reset_personality")],
                [InlineKeyboardButton(text="« Назад", callback_data="adm:home")],
            ]
            await cb.message.edit_text(text,
                                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

        elif action == "reset_personality":
            kb = [
                [InlineKeyboardButton(text="✅ Да, сбросить",
                                      callback_data="pers:reset:yes")],
                [InlineKeyboardButton(text="« Отмена", callback_data="adm:personality")],
            ]
            await cb.message.edit_text(
                "Сбросить личность к текущим дефолтам?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
            )

        elif action == "memory":
            u = await repo.upsert_user(s, cb.from_user.id,
                                       cb.from_user.username, cb.from_user.first_name)
            res = await s.execute(
                select(func.count()).select_from(Memory).where(Memory.user_id == u.id)
            )
            total = res.scalar_one()
            top = await repo.top_memories(s, u.id, limit=10)
            lines = "\n".join(f"• [{m.importance}] {m.fact}" for m in top) or "(пусто)"
            await cb.message.edit_text(
                f"<b>Память</b>\nВсего записей: <b>{total}</b>\n\n{lines}",
                reply_markup=back_btn(),
            )

        elif action == "ai":
            await cb.message.edit_text(
                f"<b>AI настройки</b>\n"
                f"Провайдер: <b>{settings.DEFAULT_PROVIDER}</b>\n"
                f"Gemini model: {settings.GEMINI_MODEL}\n"
                f"OpenAI model: {settings.OPENAI_MODEL}\n"
                f"Claude model: {settings.CLAUDE_MODEL}\n"
                f"DeepSeek model: {settings.DEEPSEEK_MODEL}\n"
                f"Ollama model: {settings.OLLAMA_MODEL}\n\n"
                f"Печатает…: {'✅' if settings.TYPING_INDICATOR else '❌'}\n"
                f"Кнопки тулов: {'✅' if settings.SHOW_TOOL_CALLS else '❌'}",
                reply_markup=back_btn(),
            )

        elif action == "provider":
            kb = [[InlineKeyboardButton(text=name, callback_data=f"prov:{name}")]
                  for name in ("g4f", "yandex", "gemini", "openai", "claude", "deepseek", "ollama")]
            kb.append([InlineKeyboardButton(text="« Назад", callback_data="adm:home")])
            await cb.message.edit_text(
                f"Текущий: <b>{settings.DEFAULT_PROVIDER}</b>\nВыбери провайдер:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
            )

        elif action == "keys":
            lines = ["<b>🔐 API ключи</b>\n"]
            for key_name, human in MANAGED_KEYS:
                v = await get_key(key_name, session=s)
                lines.append(f"• <code>{key_name}</code> — {human}: <b>{_mask(v)}</b>")
            lines.append("")
            lines.append("Чтобы установить/обновить:")
            lines.append("<code>/setkey ИМЯ ЗНАЧЕНИЕ</code>")
            lines.append("\nМожно также просить меня напрямую — я сама вызову request_api_key если понадобится.")
            await cb.message.edit_text("\n".join(lines), reply_markup=back_btn())

        elif action == "stats":
            users = (await s.execute(select(func.count()).select_from(User))).scalar_one()
            msgs = (await s.execute(select(func.count()).select_from(Message))).scalar_one()
            mems = (await s.execute(select(func.count()).select_from(Memory))).scalar_one()
            await cb.message.edit_text(
                f"<b>Статистика</b>\nПользователей: <b>{users}</b>\n"
                f"Сообщений: <b>{msgs}</b>\nФактов в памяти: <b>{mems}</b>",
                reply_markup=back_btn(),
            )

        elif action == "human":
            text, kb = render_human_panel()
            await cb.message.edit_text(text, reply_markup=kb)

        elif action == "persona":
            text, kb = render_persona_panel()
            await cb.message.edit_text(text, reply_markup=kb)

        elif action == "clear":
            kb = [
                [InlineKeyboardButton(text="🗑 Подтвердить", callback_data="clear:yes")],
                [InlineKeyboardButton(text="« Назад", callback_data="adm:home")],
            ]
            await cb.message.edit_text("Удалить всю твою память?",
                                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

        elif action == "io":
            u = await repo.upsert_user(s, cb.from_user.id, cb.from_user.username,
                                       cb.from_user.first_name)
            mems = await repo.top_memories(s, u.id, limit=1000)
            data = [{"fact": m.fact, "category": m.category,
                     "importance": m.importance, "source": m.source,
                     "date": m.created_at.isoformat()} for m in mems]
            payload = json.dumps(data, ensure_ascii=False, indent=2)
            await cb.message.edit_text(
                f"<b>Экспорт памяти</b> ({len(data)} фактов):\n<pre>{payload[:3500]}</pre>",
                reply_markup=back_btn(),
            )

    await cb.answer()

HUMAN_BOOL_FIELDS = [
    ("NO_EMDASH",           "Заменять тире на -"),
    ("HUMAN_TYPING",        "Имитация набора"),
    ("SPLIT_MESSAGES",      "Ответ неск. сообщениями"),
    ("TYPING_INDICATOR",    "Индикатор «печатает…»"),
    ("SHOW_TOOL_CALLS",     "Кнопки тулов"),
    ("REACTIONS_ENABLED",   "Эмодзи-реакции"),
    ("TYPO_ENABLED",        "Опечатки + самоисправление"),
    ("MOOD_SPEED_ENABLED",  "Настроение влияет на скорость"),
    ("READ_SILENCE_ENABLED","«Прочитала, молчит»"),
    ("STICKERS_ENABLED",    "Стикеры/кастом-эмодзи"),
    ("DATES_ENABLED",       "Памятны�� даты (поздравляет)"),
    ("JEALOUSY_ENABLED",    "Ревность/обидки (если долго молчал)"),
    ("ENERGY_ENABLED",      "Энергия/батарейка (к ночи устаёт)"),
    ("CLOSENESS_ENABLED",   "Уровень близости"),
    ("PETNAMES_ENABLED",    "Клички/пет-неймы"),
    ("WEATHER_ENABLED",     "Погода-забота (OpenWeather)"),
]
TYPING_SPEED_PRESETS = [8.0, 14.0, 20.0, 30.0]
IGNORE_CHANCE_PRESETS = [0.0, 0.12, 0.25, 0.4]

def _flag(field: str) -> str:
    return "✅" if getattr(settings, field, False) else "❌"

def render_human_panel() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "<b>🎭 Человечность / очеловечивание</b>\n\n"
        "Как живая: думает перед ответом, «печатает…», иногда отвечает не сразу.\n\n"
        f"Тире «—» -> «-»: {_flag('NO_EMDASH')}\n"
        f"Имитация набора: {_flag('HUMAN_TYPING')}\n"
        f"Скорость набора: <b>{settings.TYPING_SPEED_CPS:g}</b> симв/сек\n"
        f"Разбивка на сообщения: {_flag('SPLIT_MESSAGES')} (макс {settings.SPLIT_MAX})\n"
        f"Пауза «заметила»: {settings.READ_DELAY_MIN:g}-{settings.READ_DELAY_MAX:g} сек\n"
        f"Шанс «занята»: <b>{int(settings.IGNORE_CHANCE * 100)}%</b> "
        f"({settings.IGNORE_MIN_SECONDS:g}-{settings.IGNORE_MAX_SECONDS:g} сек)\n\n"
        "Стикеры: <code>/sticker</code> · Даты: <code>/date</code>\n"
        "Погода: <code>/weather</code> · Пет-нейм: <code>/petname</code>\n"
        "Тонкая настройка: <code>/humanset ПОЛЕ ЗНАЧЕНИЕ</code>"
    )
    rows = [[InlineKeyboardButton(text=f"{_flag(f)} {label}",
                                  callback_data=f"hum:t:{f}")]
            for f, label in HUMAN_BOOL_FIELDS]
    rows.append([
        InlineKeyboardButton(text=f"⌨️ Скорость: {settings.TYPING_SPEED_CPS:g}",
                             callback_data="hum:c:TYPING_SPEED_CPS"),
        InlineKeyboardButton(text=f"🙈 Занята: {int(settings.IGNORE_CHANCE * 100)}%",
                             callback_data="hum:c:IGNORE_CHANCE"),
    ])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="adm:home")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


# ====================== ТИПАЖ / СТАДИЯ ОТНОШЕНИЙ ======================
_RIVAL_LEVELS = ["soft", "normal", "strong"]
_RIVAL_LEVEL_LABELS = {"soft": "мягкая", "normal": "средняя", "strong": "сильная"}


def render_persona_panel() -> tuple[str, InlineKeyboardMarkup]:
    from ai.prompts import (
        PERSONA_MODE_ORDER, PERSONA_MODE_LABELS,
        RELATIONSHIP_STAGE_ORDER, RELATIONSHIP_STAGE_LABELS,
    )
    cur_mode = (getattr(settings, "PERSONA_MODE", "loving") or "loving").lower()
    cur_stage = (getattr(settings, "RELATIONSHIP_STAGE", "just_met") or "just_met").lower()
    mode_label = PERSONA_MODE_LABELS.get(cur_mode, cur_mode)
    stage_label = RELATIONSHIP_STAGE_LABELS.get(cur_stage, cur_stage)
    rival_on = bool(getattr(settings, "RIVAL_JEALOUSY_ENABLED", True))
    rlevel = (getattr(settings, "RIVAL_JEALOUSY_LEVEL", "normal") or "normal").lower()
    rlevel_label = _RIVAL_LEVEL_LABELS.get(rlevel, rlevel)
    text = (
        "<b>💠 Типаж характера и стадия отношений</b>\n\n"
        f"Режим характера: <b>{mode_label}</b>\n"
        f"Стадия отношений: <b>{stage_label}</b>\n"
        f"Ревность к соперницам: {'✅' if rival_on else '❌'} (сила: <b>{rlevel_label}</b>)\n\n"
        "Выбери типаж характера:"
    )
    rows: list[list[InlineKeyboardButton]] = []
    for m in PERSONA_MODE_ORDER:
        mark = "🔘 " if m == cur_mode else ""
        rows.append([InlineKeyboardButton(
            text=f"{mark}{PERSONA_MODE_LABELS.get(m, m)}",
            callback_data=f"pm:{m}")])
    rows.append([InlineKeyboardButton(text="— Стадия отношений —", callback_data="adm:persona")])
    stage_row: list[InlineKeyboardButton] = []
    for stg in RELATIONSHIP_STAGE_ORDER:
        mark = "🔘 " if stg == cur_stage else ""
        stage_row.append(InlineKeyboardButton(
            text=f"{mark}{RELATIONSHIP_STAGE_LABELS.get(stg, stg)}",
            callback_data=f"rs:{stg}"))
        if len(stage_row) == 2:
            rows.append(stage_row)
            stage_row = []
    if stage_row:
        rows.append(stage_row)
    rows.append([
        InlineKeyboardButton(text=f"{'✅' if rival_on else '❌'} Ревность к соперницам",
                             callback_data="rj:toggle"),
        InlineKeyboardButton(text=f"⚔️ Сила: {rlevel_label}",
                             callback_data="rj:level"),
    ])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="adm:home")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _rerender_persona(cb: CallbackQuery) -> None:
    text, kb = render_persona_panel()
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass


@router.callback_query(F.data.startswith("pm:"))
async def set_persona_mode(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    mode = cb.data.split(":", 1)[1]
    await set_behavior("PERSONA_MODE", mode)
    await _rerender_persona(cb)
    await cb.answer("Сохранено ✅")


@router.callback_query(F.data.startswith("rs:"))
async def set_rel_stage(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    stage = cb.data.split(":", 1)[1]
    await set_behavior("RELATIONSHIP_STAGE", stage)
    await _rerender_persona(cb)
    await cb.answer("Сохранено ✅")


@router.callback_query(F.data.startswith("rj:"))
async def rival_jealousy_cb(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    op = cb.data.split(":", 1)[1]
    if op == "toggle":
        cur = bool(getattr(settings, "RIVAL_JEALOUSY_ENABLED", True))
        await set_behavior("RIVAL_JEALOUSY_ENABLED", not cur)
    elif op == "level":
        cur = (getattr(settings, "RIVAL_JEALOUSY_LEVEL", "normal") or "normal").lower()
        idx = _RIVAL_LEVELS.index(cur) if cur in _RIVAL_LEVELS else 1
        await set_behavior("RIVAL_JEALOUSY_LEVEL", _RIVAL_LEVELS[(idx + 1) % len(_RIVAL_LEVELS)])
    await _rerender_persona(cb)
    await cb.answer("Сохранено ✅")


def _next_preset(presets: list[float], cur: float) -> float:
    try:
        idx = min(range(len(presets)), key=lambda i: abs(presets[i] - cur))
    except ValueError:
        return cur
    return presets[(idx + 1) % len(presets)]


@router.callback_query(F.data.startswith("hum:"))
async def human_cb(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Нет доступа", show_alert=True)
        return
    _, op, field = cb.data.split(":", 2)
    if op == "t":
        cur = bool(getattr(settings, field, False))
        await set_behavior(field, not cur)
    elif op == "c":
        if field == "TYPING_SPEED_CPS":
            presets = TYPING_SPEED_PRESETS
        elif field == "IGNORE_CHANCE":
            presets = IGNORE_CHANCE_PRESETS
        else:
            presets = []
        if presets:
            cur = float(getattr(settings, field, presets[0]))
            await set_behavior(field, _next_preset(presets, cur))
    text, kb = render_human_panel()
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await cb.answer("Сохранено ✅")


@router.callback_query(F.data == "pers:reset:yes")
async def do_reset_personality(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return
    async with SessionLocal() as s:
        await repo.update_personality(s, **PERSONALITY_DEFAULTS)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="« Назад", callback_data="adm:personality")
    ]])
    await cb.message.edit_text(
        "Личность сброшена к дефолтам.",
        reply_markup=kb,
    )
    await cb.answer("Готово", show_alert=False)

@router.callback_query(F.data.startswith("prov:"))
async def switch_provider(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return
    name = cb.data.split(":", 1)[1]
    async with SessionLocal() as s:
        await repo.set_setting(s, "default_provider", name)
    try:
        settings.DEFAULT_PROVIDER = name
    except Exception:
        pass
    try:
        from ai.core import AICore
        from ai.providers.factory import build_provider
        from handlers.messages import _core as core
        core.provider = build_provider()
    except Exception:
        pass
    await cb.answer(f"Провайдер: {name}", show_alert=False)

@router.callback_query(F.data == "clear:yes")
async def confirm_clear(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return
    async with SessionLocal() as s:
        u = await repo.upsert_user(s, cb.from_user.id, cb.from_user.username,
                                   cb.from_user.first_name)
        n = await memory_clear(s, u.id)
    await cb.message.edit_text(f"Удалено записей: <b>{n}</b>",
                               reply_markup=back_btn())
    await cb.answer()

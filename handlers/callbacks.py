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
from utils.settings_kv import get_key

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
            res = await s.execute(select(func.count()).select_from(Memory))
            total = res.scalar_one()
            top = await repo.top_memories(s, cb.from_user.id, limit=10)
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

"""Основной обработчик сообщений: диалог, стикеры, голос и человеко-подобные ответы."""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
import time

import re

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup,
                            InlineKeyboardButton, FSInputFile, URLInputFile)
from aiogram.utils.chat_action import ChatActionSender

from config import settings
from db.session import SessionLocal
from db import repo
from ai.core import AICore, Turn, ToolTrace, Attachment
from handlers import lib_download, steam_flow
from utils.humanize import send_humanlike, maybe_react
from utils.logger import log
from utils.settings_kv import set_key, get_key
from utils import stickers

router = Router(name="messages")
_core = AICore()

_DEBOUNCE_SECONDS = 2.5
_MSG_BUFFER: dict[int, dict] = {}

_KEY_SETUP_FLOWS: dict[str, dict] = {
    "yandex": {
        "key_name": "YANDEX_API_KEY",
        "display":  "🇷🇺 Yandex GPT",
        "url":      "https://console.yandex.cloud",
        "free":     True,
        "steps": (
            "<b>🇷🇺 Yandex AI Studio</b> — бесплатно, без карты.\n\n"
            "1. Открой <a href='https://console.yandex.cloud'>console.yandex.cloud</a>.\n"
            "2. Каталоги → скопируй ID нужного каталога (b1g…) и пришли одной строкой:\n"
            "   <code>/setkey YANDEX_FOLDER b1g...</code>\n"
            "3. Сервисные аккаунты → создай СА с ролью <code>ai.languageModels.user</code>.\n"
            "4. У СА → API ключи → «Создать API-ключ» → скопируй (AQVN…).\n\n"
            "<b>Теперь пришли мне ключ следующим сообщением — просто одной строкой, без /setkey.</b>\n"
            "Я сохраню его и сама переключусь на Yandex. 🌸"
        ),
    },
    "gemini": {
        "key_name": "GEMINI_API_KEY",
        "display":  "🌸 Google Gemini",
        "url":      "https://aistudio.google.com/apikey",
        "free":     True,
        "steps": (
            "<b>🌸 Google Gemini</b> — бесплатно, ~60 запросов/мин.\n\n"
            "1. Открой <a href='https://aistudio.google.com/apikey'>aistudio.google.com/apikey</a>.\n"
            "2. Войди Google-аккаунтом.\n"
            "3. «Create API key» → скопируй (AIza…).\n\n"
            "<b>Пришли ключ следующим сообщением одной строкой.</b>"
        ),
    },
    "deepseek": {
        "key_name": "DEEPSEEK_API_KEY",
        "display":  "💸 DeepSeek",
        "url":      "https://platform.deepseek.com",
        "free":     False,
        "steps": (
            "<b>💸 DeepSeek</b> — очень дёшево (~$0.1 / 1M токенов), нужна карта.\n\n"
            "1. <a href='https://platform.deepseek.com'>platform.deepseek.com</a> → API Keys → Create (sk-…).\n\n"
            "<b>Пришли ключ следующим сообщением одной строкой.</b>"
        ),
    },
    "openai": {
        "key_name": "OPENAI_API_KEY",
        "display":  "🎭 OpenAI GPT-4",
        "url":      "https://platform.openai.com/api-keys",
        "free":     False,
        "steps": (
            "<b>🎭 OpenAI</b> — платно, минимум $5 на баланс.\n\n"
            "1. <a href='https://platform.openai.com/api-keys'>platform.openai.com/api-keys</a> → Create secret key (sk-…).\n"
            "2. Billing → пополни минимум $5, иначе 429.\n\n"
            "<b>Пришли ключ следующим сообщением одной строкой.</b>"
        ),
    },
    "claude": {
        "key_name": "ANTHROPIC_API_KEY",
        "display":  "🎭 Anthropic Claude",
        "url":      "https://console.anthropic.com",
        "free":     False,
        "steps": (
            "<b>🎭 Claude</b> — платно.\n\n"
            "1. <a href='https://console.anthropic.com'>console.anthropic.com</a> → API Keys → Create (sk-ant-…).\n\n"
            "<b>Пришли ключ следующим сообщением одной строкой.</b>"
        ),
    },
}

_PENDING_KEY: dict[int, dict] = {}
_PENDING_KEY_TTL = 600
_G4F_SKIPPED: dict[int, set[str]] = {}

_G4F_PROVIDER_INFO: dict[str, dict] = {
    "OpenRouter":      {"url": "https://openrouter.ai/keys",              "hint": "sk-or-…",  "free": True},
    "OpenaiChat":      {"url": "https://chat.openai.com",                 "hint": "cookies (.har)", "free": True},
    "PuterJS":         {"url": "https://puter.com",                       "hint": "token",     "free": True},
    "ApiAirforce":     {"url": "https://api.airforce",                    "hint": "api key",   "free": True},
    "Airforce":        {"url": "https://api.airforce",                    "hint": "api key",   "free": True},
    "HuggingChat":     {"url": "https://huggingface.co/settings/tokens",  "hint": "hf_…",     "free": True},
    "HuggingFace":     {"url": "https://huggingface.co/settings/tokens",  "hint": "hf_…",     "free": True},
    "Cerebras":        {"url": "https://cloud.cerebras.ai",               "hint": "csk-…",    "free": True},
    "Groq":            {"url": "https://console.groq.com/keys",           "hint": "gsk_…",    "free": True},
    "DeepInfraChat":   {"url": "https://deepinfra.com/dash/api_keys",     "hint": "di-…",     "free": False},
    "CopilotAccount":  {"url": "https://github.com/copilot",              "hint": "gh cookies", "free": False},
    "GithubCopilot":   {"url": "https://github.com/copilot",              "hint": "gh cookies", "free": False},
    "MetaAIAccount":   {"url": "https://meta.ai",                         "hint": "cookies",   "free": True},
    "Poe":             {"url": "https://poe.com",                         "hint": "cookies",   "free": True},
    "Gemini":          {"url": "https://gemini.google.com",               "hint": "cookies",   "free": True},
    "Reka":            {"url": "https://chat.reka.ai",                    "hint": "api key",   "free": True},
    "Replicate":       {"url": "https://replicate.com/account/api-tokens","hint": "r8_…",     "free": False},
    "nGPT":            {"url": "https://www.ngpt.chat",                   "hint": "api key",   "free": True},
    "WeWordle":        {"url": "https://wewordle.org",                    "hint": "—",         "free": True},
}

async def _saved_key_set() -> set[str]:
    saved: set[str] = set()
    for pid, flow in _KEY_SETUP_FLOWS.items():
        try:
            v = await get_key(flow["key_name"])
        except Exception:
            v = None
        if v:
            saved.add(flow["key_name"])
    for name in _G4F_PROVIDER_INFO:
        kn = f"G4F_KEY_{name.upper()}"
        try:
            v = await get_key(kn)
        except Exception:
            v = None
        if v:
            saved.add(kn)
    return saved

async def _build_keys_menu(header: str = "") -> tuple[str, InlineKeyboardMarkup]:
    saved = await _saved_key_set()

    total = len(_KEY_SETUP_FLOWS) + len(_G4F_PROVIDER_INFO)
    lines: list[str] = []
    if header:
        lines.append(header)
        lines.append("")
    lines.append(f"🔐 <b>Ключи провайдеров</b> — сохранено <b>{len(saved)}</b> из {total}.")
    lines.append("Тыкай любого → инструкция → пришли ключ. Можно зарегаться подряд на всех — после каждого ключа меню возвращается.")
    lines.append("")
    lines.append("<b>Встроенные провайдеры</b> (полноценный API, стабильно):")

    rows: list[list[InlineKeyboardButton]] = []

    row: list[InlineKeyboardButton] = []
    for pid, flow in _KEY_SETUP_FLOWS.items():
        if flow["key_name"] in saved:
            mark = "✅"
        elif flow.get("free"):
            mark = "🆓"
        else:
            mark = "🔑"
        row.append(InlineKeyboardButton(
            text=f"{mark} {flow['display']}",
            callback_data=f"keysetup:{pid}",
        ))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        text="── g4f суб-провайдеры ──", callback_data="keysetup:noop",
    )])

    row = []
    for name, info in _G4F_PROVIDER_INFO.items():
        kn = f"G4F_KEY_{name.upper()}"
        if kn in saved:
            mark = "✅"
        elif info.get("free"):
            mark = "🆓"
        else:
            mark = "🔑"
        row.append(InlineKeyboardButton(
            text=f"{mark} {name}",
            callback_data=f"g4fkey:{name}",
        ))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(text="⚙️ Выбрать активного /admin", callback_data="adm:provider"),
        InlineKeyboardButton(text="✅ Закрыть", callback_data="keysetup:close"),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)

_G4F_RECOMMENDED = ["OpenRouter", "Groq", "Cerebras", "HuggingFace", "Gemini", "Airforce"]

def _parse_g4f_needy(err_txt: str) -> list[str]:
    m = re.search(r"<!G4F_AUTH_NEEDED:([^!]*)!>", err_txt or "")
    return [n for n in (m.group(1).split("|") if m else []) if n]

async def _pick_g4f_provider(user_id: int, needy: list[str]) -> str | None:
    """Выбрать ОДНОГО провайдера, у которого ещё нет ключа и которого не пропустили."""
    saved = await _saved_key_set()
    skipped = _G4F_SKIPPED.get(user_id, set())
    order: list[str] = []
    for group in (needy, _G4F_RECOMMENDED, list(_G4F_PROVIDER_INFO.keys())):
        for n in group:
            if n not in order:
                order.append(n)
    for n in order:
        if n not in _G4F_PROVIDER_INFO:
            continue
        if f"G4F_KEY_{n.upper()}" in saved or n in skipped:
            continue
        return n
    return None

async def _send_g4f_setup_prompt(msg: Message, err_txt: str,
                                 user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else (msg.from_user.id if msg.from_user else 0)
    needy = _parse_g4f_needy(err_txt)
    name = await _pick_g4f_provider(uid, needy)

    if not name:
        _G4F_SKIPPED.pop(uid, None)
        text, kb = await _build_keys_menu(
            header=("😥 Ок, ключи пропустили. Можешь подключить встроенный "
                    "<b>🇷🇺 Yandex</b> или <b>🌸 Gemini</b> — или вот весь список:")
        )
        await msg.answer(text, reply_markup=kb, disable_web_page_preview=True)
        return

    info = _G4F_PROVIDER_INFO.get(name) or {"url": "https://openrouter.ai/keys",
                                            "hint": "api key", "free": None}
    url = info.get("url") or "https://openrouter.ai/keys"
    free_note = ("бесплатно" if info.get("free") is True
                 else "платно" if info.get("free") is False else "")
    head = "😥 Бесплатные g4f-бэкенды сей��ас недоступны — одному нужен ключ."
    if needy:
        head += f"\n🔐 Просят вход: <i>{', '.join(sorted(set(needy))[:6])}</i>"
    text = (
        f"{head}\n\n"
        f"<b>🔑 {name}</b>" + (f" — <i>{free_note}</i>" if free_note else "") + "\n"
        f"1. Зарегайся: <a href='{url}'>{url}</a>\n"
        f"2. Скопируй ключ (<code>{info.get('hint', 'api key')}</code>) и пришли следующим сообщением.\n\n"
        f"Не хочешь — жми «Пропустить», предложу другого."
    )
    rows = [
        [InlineKeyboardButton(text="🔑 Ввести ключ", callback_data=f"g4fkey:{name}")],
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"g4fskip:{name}"),
         InlineKeyboardButton(text="🌐 Сайт", url=url)],
        [InlineKeyboardButton(text="📋 Все ключи", callback_data="keysetup:menu")],
    ]
    await msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                     disable_web_page_preview=True)

@router.callback_query(F.data.startswith("keysetup:"))
async def cb_keysetup(cb: CallbackQuery):
    if cb.data == "keysetup:cancel":
        _PENDING_KEY.pop(cb.from_user.id, None)
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        text, kb = await _build_keys_menu(header="Ок, отменила. Выбирай другого:")
        await cb.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
        await cb.answer()
        return

    if cb.data == "keysetup:close":
        _PENDING_KEY.pop(cb.from_user.id, None)
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await cb.answer("Готово ✨")
        return

    if cb.data == "keysetup:menu":
        text, kb = await _build_keys_menu()
        await cb.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
        await cb.answer()
        return

    if cb.data == "keysetup:noop":
        await cb.answer()
        return

    pid = cb.data.split(":", 1)[1]
    flow = _KEY_SETUP_FLOWS.get(pid)
    if not flow:
        await cb.answer("Неизвестный провайдер", show_alert=True)
        return

    _PENDING_KEY[cb.from_user.id] = {
        "key_name":    flow["key_name"],
        "provider_id": pid,
        "display":     flow["display"],
        "ts":          time.time(),
    }
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🌐 Открыть сайт", url=flow["url"]),
        InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="keysetup:cancel"),
    ]])
    await cb.message.answer(flow["steps"], reply_markup=kb, disable_web_page_preview=True)
    await cb.answer(f"Жду ключ для {flow['display']}")

@router.callback_query(F.data.startswith("g4fkey:"))
async def cb_g4fkey(cb: CallbackQuery):
    name = cb.data.split(":", 1)[1]
    info = _G4F_PROVIDER_INFO.get(name) or {
        "url":  f"https://www.google.com/search?q={name}+api+key",
        "hint": "api key",
        "free": None,
    }
    key_name = f"G4F_KEY_{name.upper()}"

    _PENDING_KEY[cb.from_user.id] = {
        "key_name":      key_name,
        "provider_id":   "g4f",
        "display":       f"g4f→{name}",
        "ts":            time.time(),
        "keep_provider": True,
    }

    free_note = "бесплатно" if info.get("free") is True else ("платно" if info.get("free") is False else "")
    header = f"<b>🔑 {name}</b>" + (f" — <i>{free_note}</i>" if free_note else "")

    text = (
        f"{header}\n\n"
        f"1. Зарегайся: <a href='{info['url']}'>{info['url']}</a>\n"
        f"2. Скопируй ключ (формат: <code>{info['hint']}</code>).\n\n"
        f"<b>Пришли ключ следующим сообщением — одной строкой.</b>\n"
        f"Я сохраню его как <code>{key_name}</code> и g4f будет использовать его "
        f"когда снова попадёт на <b>{name}</b>. 🌸"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🌐 Открыть сайт", url=info["url"]),
        InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="keysetup:cancel"),
    ]])
    await cb.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    await cb.answer(f"Жду ключ для {name}")

@router.callback_query(F.data.startswith("g4fskip:"))
async def cb_g4fskip(cb: CallbackQuery):
    name = cb.data.split(":", 1)[1]
    _G4F_SKIPPED.setdefault(cb.from_user.id, set()).add(name)
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.answer("Ок, пропустила")
    await _send_g4f_setup_prompt(cb.message, "", user_id=cb.from_user.id)

TOOL_CACHE: dict[str, tuple[str, dict, float]] = {}
_TOOL_CACHE_TTL = 3600

TOOL_ICONS = {
    "web_search":      "🌐",
    "google_search":   "🔍",
    "steam_search":    "🎮",
    "steam_game":      "🎮",
    "anime_search":    "🌸",
    "anime_info":      "📖",
    "anime_tracking":  "📌",
    "lib_search":      "📚",
    "lib_info":        "📖",
    "lib_download":    "⬇️",
    "memory_save":     "🧠",
    "image_vision":    "👁️",
    "weather":         "🌦️",
    "request_api_key": "🔐",
}

def _short_id(name: str, args: dict) -> str:
    raw = f"{name}:{json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)}:{time.time()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]

def _cache_gc() -> None:
    if len(TOOL_CACHE) < 200:
        return
    now = time.time()
    dead = [k for k, v in TOOL_CACHE.items() if now - v[2] > _TOOL_CACHE_TTL]
    for k in dead:
        TOOL_CACHE.pop(k, None)

def _tools_keyboard(tools: list[ToolTrace]) -> InlineKeyboardMarkup | None:
    if not tools:
        return None
    _cache_gc()
    rows = []
    for t in tools:
        tid = _short_id(t.name, t.arguments)
        TOOL_CACHE[tid] = (t.name, t.arguments, time.time())
        icon = TOOL_ICONS.get(t.name, "🔧")
        label = f"{icon} {t.name}"
        if t.summary:
            label += f": {t.summary}"
        if not t.ok:
            label = "⚠️ " + label
        rows.append([InlineKeyboardButton(text=label[:60], callback_data=f"tool:{tid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _allowed(tg_id: int) -> bool:
    ids = settings.admin_ids
    return (not ids) or (tg_id in ids)

async def _send_attachments(msg: Message, attachments: list[Attachment]) -> None:
    for att in attachments:
        try:
            if att.kind == "file" and att.path and os.path.exists(att.path):
                await msg.answer_document(
                    FSInputFile(att.path),
                    caption=(att.caption or "")[:1000] or None,
                )
            elif att.kind == "photo" and (att.url or (att.path and os.path.exists(att.path))):
                if att.url:
                    await msg.answer_photo(URLInputFile(att.url),
                                           caption=(att.caption or "")[:1000] or None)
                else:
                    await msg.answer_photo(FSInputFile(att.path),
                                           caption=(att.caption or "")[:1000] or None)
            elif att.kind == "message" and att.text:
                await msg.answer(att.text[:4000])
        except Exception:
            log.exception("send_attachment failed")

@router.message(CommandStart())
async def start(msg: Message):
    if msg.from_user is None:
        return
    if not _allowed(msg.from_user.id):
        log.info(f"[deny] /start от чужого tg_id={msg.from_user.id}")
        await msg.answer("Привет! Я — ��ичный компаньон и общаюсь только со своим владельцем 🌸")
        return
    async with SessionLocal() as s:
        await repo.upsert_user(s, msg.from_user.id, msg.from_user.username,
                               msg.from_user.first_name)
        p = await repo.get_personality(s)
    await msg.answer(
        f"Привет, я {p.name} 🌸\n"
        f"{p.description}\n\n"
        "Пиши просто как человеку. Могу поболтать, поискать аниме/мангу/игры в Стиме, "
        "скачать мангу PDF-кой, погуглить в интернете и разобрать твои картинки."
    )

@router.message(Command("keys"))
async def cmd_keys(msg: Message):
    if msg.from_user is None or not _allowed(msg.from_user.id):
        return
    text, kb = await _build_keys_menu(
        header="🌸 Регистрируйся на всех подряд — я запомню каждый ключ."
    )
    await msg.answer(text, reply_markup=kb, disable_web_page_preview=True)

@router.message(Command("setkey"))
async def cmd_setkey(msg: Message):
    if not _allowed(msg.from_user.id):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer(
            "Формат: <code>/setkey ИМЯ ЗНАЧЕНИЕ</code>\n"
            "Например:\n"
            "<code>/setkey GOOGLE_API_KEY AIza…</code>\n"
            "<code>/setkey GOOGLE_CX 0123…</code>\n"
            "<code>/setkey MANGALIB_TOKEN eyJ…</code>\n"
            "<code>/setkey GEMINI_API_KEY AIza…</code>"
        )
        return
    name, value = parts[1].strip(), parts[2].strip()
    await set_key(name, value)
    try:
        await msg.delete()
    except Exception:
        pass
    await msg.answer(f"Сохранила <b>{name}</b> — могу пользоваться сразу.")
    log.info(f"🔐 ключ сохранён: {name}")

_PENDING_STICKER: dict[int, dict] = {}
_STICKER_SLOTS = tuple(stickers.MOOD_SLOTS)


def _extract_sticker_id(m) -> tuple[str, str] | None:
    """Из сообщения-ответа достаёт id стикера или кастом-эмодзи."""
    st = getattr(m, "sticker", None)
    if st is not None:
        cem = getattr(st, "custom_emoji_id", None)
        if cem:
            return ("custom", str(cem))
        return ("sticker", st.file_id)
    for e in (getattr(m, "entities", None) or []):
        if getattr(e, "type", "") == "custom_emoji" and getattr(e, "custom_emoji_id", None):
            return ("custom", str(e.custom_emoji_id))
    return None


def _sticker_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить стикер/пак", callback_data="stkhelp:add")],
        [InlineKeyboardButton(text="🚫 Убрать цветочек", callback_data="stkhelp:off")],
    ])


def _pack_slots_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, s in enumerate(_STICKER_SLOTS, 1):
        row.append(InlineKeyboardButton(text=s, callback_data=f"stkpack:{s}"))
        if i % 3 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✖ отмена", callback_data="stkpack:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sticker_slots_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, s in enumerate(_STICKER_SLOTS, 1):
        row.append(InlineKeyboardButton(text=s, callback_data=f"stkslot:{s}"))
        if i % 3 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✖ отмена", callback_data="stkslot:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("sticker"))
async def cmd_sticker(msg: Message):
    if msg.from_user is None or not _allowed(msg.from_user.id):
        return
    parts = (msg.text or "").split()
    args = [p.lower() for p in parts[1:]]
    reply = msg.reply_to_message

    if args and args[0] in ("off", "nodefault"):
        await stickers.disable_defaults()
        await msg.answer("Ок, стандартный цветочек больше не буду слать 🌸→🚫")
        return
    if args and args[0] in ("clear", "clr"):
        slot = args[1] if len(args) > 1 else "any"
        n = await stickers.clear_slot(slot)
        await msg.answer(f"Очистила набор <b>{slot}</b> ({n} шт).")
        return

    if reply is None:
        data = await stickers.get_all()
        lines = [f"• {k}: {len(v)}" for k, v in data.items() if v]
        cur = "\n".join(lines) or "(пусто)"
        await msg.answer(
            "🏷 <b>Стикеры по настроению</b>\n\n"
            f"{cur}\n\n"
            "Добавить: ответь на стикер/кастом-эмодзи командой <code>/sticker</code> "
            "(покажу кнопки настроений) или сразу <code>/sticker loving</code>.\n"
            "Убрать дефолтный цветочек: <code>/sticker off</code>\n"
            "Очистить набор: <code>/sticker clear loving</code>",
            reply_markup=_sticker_menu_kb(),
        )
        return

    got = _extract_sticker_id(reply)
    if got is None:
        await msg.answer("Это не стикер и не кастом-эмодзи 🤔 Ответь командой на стикер.")
        return
    kind, sid = got
    if args and args[0] in _STICKER_SLOTS:
        ok = await stickers.add_sticker(args[0], sid)
        await msg.answer(f"{'Добавила' if ok else 'Уже есть'} в набор <b>{args[0]}</b> 🌸")
        return
    _PENDING_STICKER[msg.from_user.id] = {"sid": sid, "kind": kind, "ts": time.time()}
    await msg.answer("В какое настроение сохранить этот стикер?", reply_markup=_sticker_slots_kb())


@router.callback_query(F.data.startswith("stkslot:"))
async def cb_stkslot(cb: CallbackQuery):
    slot = cb.data.split(":", 1)[1]
    if slot == "cancel":
        _PENDING_STICKER.pop(cb.from_user.id, None)
        await cb.message.edit_text("Отменила 🙂")
        await cb.answer()
        return
    pend = _PENDING_STICKER.pop(cb.from_user.id, None)
    if not pend or time.time() - pend["ts"] > 600:
        await cb.answer("Стикер потерялся, попробуй ещё раз", show_alert=True)
        return
    ok = await stickers.add_sticker(slot, pend["sid"])
    await cb.message.edit_text(f"{'Добавила' if ok else 'Уже был'} в набор <b>{slot}</b> 🌸")
    await cb.answer("Готово")


_PENDING_PACK: dict[int, dict] = {}


async def _collect_pack_ids(bot, set_name: str) -> list[str]:
    """Собирает id всех стикеров пака (file_id или custom_emoji_id)."""
    try:
        s = await bot.get_sticker_set(set_name)
    except Exception as e:
        log.warning(f"🏷 не смогла загрузить пак {set_name}: {e}")
        return []
    ids: list[str] = []
    for st in (getattr(s, "stickers", None) or []):
        cem = getattr(st, "custom_emoji_id", None)
        ids.append(str(cem) if cem else st.file_id)
    return ids


@router.message(F.sticker)
async def on_sticker(msg: Message):
    if msg.from_user is None or not _allowed(msg.from_user.id):
        return
    st = msg.sticker
    set_name = getattr(st, "set_name", None)
    cem = getattr(st, "custom_emoji_id", None)
    single_id = str(cem) if cem else st.file_id
    _PENDING_PACK[msg.from_user.id] = {
        "ts": time.time(), "single": single_id, "set_name": set_name,
    }
    if set_name:
        await msg.answer(
            f"🏷 Стикер из пака <b>{set_name}</b>. В какое настроение сохранить <b>весь пак</b>?\n"
            "(а если нужен только этот один - ответь на него командой <code>/sticker</code>)",
            reply_markup=_pack_slots_kb(),
        )
    else:
        await msg.answer(
            "🏷 Одиночный стикер (без пака). В какое настроение сохранить?",
            reply_markup=_pack_slots_kb(),
        )


@router.callback_query(F.data.startswith("stkpack:"))
async def cb_stkpack(cb: CallbackQuery):
    slot = cb.data.split(":", 1)[1]
    if slot == "cancel":
        _PENDING_PACK.pop(cb.from_user.id, None)
        await cb.message.edit_text("Отменила 🙂")
        await cb.answer()
        return
    pend = _PENDING_PACK.pop(cb.from_user.id, None)
    if not pend or time.time() - pend["ts"] > 600:
        await cb.answer("Стикер потерялся, попробуй ещё раз", show_alert=True)
        return
    set_name = pend.get("set_name")
    if set_name:
        await cb.message.edit_text(f"Импортирую пак <b>{set_name}</b>… ⏳")
        ids = await _collect_pack_ids(cb.bot, set_name)
        if not ids:
            ids = [pend["single"]]
        added = await stickers.add_many(slot, ids)
        await cb.message.edit_text(
            f"🏷 Импортировала пак <b>{set_name}</b> в набор <b>{slot}</b>: "
            f"+{added} (всего в паке {len(ids)}) 🌸"
        )
    else:
        ok = await stickers.add_sticker(slot, pend["single"])
        await cb.message.edit_text(f"{'Добавила' if ok else 'Уже был'} стикер в набор <b>{slot}</b> 🌸")
    await cb.answer("Готово")


@router.callback_query(F.data.startswith("stkhelp:"))
async def cb_stkhelp(cb: CallbackQuery):
    action = cb.data.split(":", 1)[1]
    if action == "off":
        await stickers.disable_defaults()
        await cb.message.edit_text("Ок, стандартный цветочек больше не буду слать 🌸→🚫")
        await cb.answer()
        return
    if action == "add":
        await cb.message.answer(
            "Пришли мне <b>любой стикер</b> - если он из пака, предложу импортировать <b>весь пак</b> "
            "в выбранное настроение. Или ответь на стикер командой <code>/sticker</code> - добавлю только его."
        )
        await cb.answer()


@router.message(F.photo | F.text)
async def any_message(msg: Message):
    if msg.from_user is None:
        return
    if not _allowed(msg.from_user.id):
        log.info(f"[deny] сообщение от чужого tg_id={msg.from_user.id}")
        return

    pending = _PENDING_KEY.get(msg.from_user.id)
    if pending and msg.text and not msg.text.strip().startswith("/"):
        if time.time() - pending["ts"] > _PENDING_KEY_TTL:
            _PENDING_KEY.pop(msg.from_user.id, None)
        else:
            _PENDING_KEY.pop(msg.from_user.id, None)
            token    = msg.text.strip()
            key_name = pending["key_name"]
            pid      = pending["provider_id"]
            display  = pending["display"]
            try:
                await set_key(key_name, token)
            except Exception:
                log.exception("pending key save failed")
                await msg.answer("Не удалось сохранить ключ 😢 Попробуй ещё раз через /keys.")
                return
            try:
                await msg.delete()
            except Exception:
                pass
            if key_name.startswith("G4F_KEY_"):
                prov_up = key_name[len("G4F_KEY_"):]
                real = next((n for n in _G4F_PROVIDER_INFO if n.upper() == prov_up), prov_up)
                _G4F_SKIPPED.pop(msg.from_user.id, None)
                try:
                    reset = getattr(getattr(_core, "provider", None), "reset_provider_auth", None)
                    if reset:
                        reset(real)
                except Exception:
                    log.exception("reset_provider_auth failed")
                await msg.answer(
                    f"✅ Сохранила ключ для <b>{real}</b> — g4f будет юзать его. "
                    "Напиши сообщение ещё раз, и я отвечу через него 🌸"
                )
                log.info(f"🔐 g4f-ключ сохранён: {key_name} → provider={real}")
                return
            text, kb = await _build_keys_menu(
                header=(
                    f"✅ Сохранила <code>{key_name}</code> для <b>{display}</b>.\n"
                    "Можешь тыкнуть ещё одного провайдера — или закрыть меню и писать боту."
                )
            )
            await msg.answer(text, reply_markup=kb, disable_web_page_preview=True)
            log.info(f"🔐 pending-ключ сохранён: {key_name} → provider={pid}")
            return

    if msg.text and msg.text.strip().startswith("/"):
        log.info(f"[cmd] игнорирую необработанную команду: {msg.text.strip()[:32]!r}")
        return

    images: list[bytes] = []
    if msg.photo:
        try:
            largest = msg.photo[-1]
            file = await msg.bot.get_file(largest.file_id)
            buf = await msg.bot.download_file(file.file_path)
            images.append(buf.read())
        except Exception:
            log.exception("не смогла скачать картинку")
    text = msg.text or msg.caption or ("[картинка]" if images else "")
    if not text and not images:
        return

    # Он просит глянуть на его экран — делаем скриншот ПРЯМО СЕЙЧАС и прикладываем к Turn
    if not images and _wants_screen_look(text):
        try:
            from utils.screen import capture_screen_jpeg, screen_available
            if screen_available():
                shot = capture_screen_jpeg()
                if shot:
                    images.append(shot)
                    text = (text or "").strip() + \
                        "\n[Он просит посмотреть на его экран — приложен скриншот его экрана прямо сейчас, живо отреагируй на то, что видишь]"
                    log.info("\U0001f4f8 сделала скриншот по просьбе")
                else:
                    text = (text or "").strip() + \
                        "\n[Он просит посмотреть на экран, но сейчас не получилось сделать снимок — мягко скажи об этом]"
            else:
                text = (text or "").strip() + \
                    "\n[Он просит посмотреть на экран, но доступа к экрану сейчас нет — мягко скажи об этом]"
        except Exception:
            log.exception("screen look on demand failed")

    # Он явно просит стикер — отправим его сами (и попросим модель не отнекиваться)
    if _wants_sticker(text):
        text = (text or "").strip() + \
            "\n[Он просит стикер — стикер будет отправлен автоматически. Просто тепло отреагируй одной короткой фразой и НЕ говори, что не умеешь отправлять стикеры.]"

    r = msg.reply_to_message
    if r is not None:
        quoted = (r.text or r.caption or "").strip()
        if quoted:
            who = "Mahiru" if (r.from_user and getattr(r.from_user, "is_bot", False)) else "он"
            text = f"[в ответ на сообщение {who}: «{quoted[:300]}»]\n{text}".strip()

    await _buffer_and_schedule(msg, text, images)


async def _buffer_and_schedule(msg: Message, text: str, images: list[bytes]) -> None:
    """Копим быстрые сообщения пользователя и отвечаем на них ОДНИМ разом."""
    tg_id = msg.from_user.id
    buf = _MSG_BUFFER.get(tg_id)
    if buf is None:
        buf = {"texts": [], "images": [], "task": None, "msg": msg}
        _MSG_BUFFER[tg_id] = buf
    buf["msg"] = msg
    if text:
        buf["texts"].append(text)
    if images:
        buf["images"].extend(images)
    old = buf.get("task")
    if old and not old.done():
        old.cancel()
    buf["task"] = asyncio.create_task(_flush_after_delay(tg_id))


async def _flush_after_delay(tg_id: int) -> None:
    try:
        await asyncio.sleep(_DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        return
    buf = _MSG_BUFFER.pop(tg_id, None)
    if not buf:
        return
    texts = [t for t in buf["texts"] if t]
    combined = "\n".join(texts).strip()
    images = buf["images"] or None
    last_msg = buf["msg"]
    if not combined and not images:
        return
    if len(texts) > 1:
        log.info(f"🧵 склеила {len(texts)} сообщений в один ответ (tg_id={tg_id})")
    try:
        await _run_chat(last_msg, combined, images)
    except Exception:
        log.exception("_run_chat упал")


_VOICE_REQ_RE = re.compile(
    r"(голосов|голоском|своим голос|озвуч|скажи вслух|проговори|\bвойс\b|аудио сообщени|голосом)",
    re.IGNORECASE,
)


def _wants_voice(text: str) -> bool:
    """Явная просьба ответить голосом."""
    return bool(text and _VOICE_REQ_RE.search(text))


# Слова про экран — с терпимостью к опечаткам (экран/экрна/екран/монитор/дисплей/screen/скрин/десктоп/рабочий стол)
_SCREEN_WORD_RE = re.compile(
    r"(экр\w*|екр\w*|монитор\w*|дисплей\w*|дисплэй\w*|\bscreen\b|скрин\w*|десктоп\w*|рабоч\w+\s+стол\w*)",
    re.IGNORECASE,
)
# Глаголы «посмотреть/глянуть»
_SCREEN_VERB_RE = re.compile(
    r"(глян|гляд|взгл|посмотр|смотр|погля|увид|зыр|чекни|зацен)",
    re.IGNORECASE,
)
# «что у меня / чем я занят / что я делаю» — без явного слова «экран»
_SCREEN_ACTIVITY_RE = re.compile(
    r"(что (у меня|там у меня|происходит у меня)|чем я (зан|занима)|что я (дела|делаю))",
    re.IGNORECASE,
)


def _wants_screen_look(text: str) -> bool:
    """Просьба посмотреть на экран.

    Срабатывает на «глянь на экран», «что у меня на экране?»,
    «посмотри на мой экрна» (опечатка) и подобное — терпима к опечаткам
    и порядку слов. Срабатывает, если есть слово про экран, либо связка
    «глагол-посмотреть + что я делаю».
    """
    if not text:
        return False
    t = text.lower()
    if _SCREEN_WORD_RE.search(t):
        return True
    return bool(_SCREEN_VERB_RE.search(t) and _SCREEN_ACTIVITY_RE.search(t))


# Явная просьба прислать стикер
_STICKER_REQ_RE = re.compile(
    r"(стикер\w*|стикос\w*|наклейк\w*|пришли\s+смайл|кинь\s+смайл|отправь\s+смайл)",
    re.IGNORECASE,
)


def _wants_sticker(text: str) -> bool:
    """Явная просьба прислать стикер («отправь стикер», «кинь стикерок»)."""
    return bool(text and _STICKER_REQ_RE.search(text))


async def _run_chat(msg: Message, text: str, images: list[bytes] | None) -> None:
    """Единая обработка (склеенного) сообщения: интенты, LLM, ответ."""
    cur_mood = None
    answer = ""
    tools_used = []
    attachments = None
    async with SessionLocal() as s:
        user = await repo.upsert_user(s, msg.from_user.id, msg.from_user.username,
                                      msg.from_user.first_name)
        try:
            _ms = await repo.get_mood(s, user.id)
            cur_mood = getattr(_ms, "mood", None)
        except Exception:
            cur_mood = None
        try:
            await maybe_react(msg, cur_mood)
        except Exception:
            pass

        if not text and images:
            text = "[картинка]"
        if not text and not images:
            return

        if not images and text:
            intent = lib_download.detect_download_intent(text)
            if intent:
                target = await lib_download.resolve_download_target(s, user.id, text, intent)
                if target:
                    kind, query = target
                    await repo.add_message(s, user.id, "user", text)
                    await lib_download.start_download_flow(msg, user.id, kind, query)
                    return

            follow = await lib_download.maybe_followup_download(s, user.id, text)
            if follow:
                kind, query = follow
                await repo.add_message(s, user.id, "user", text)
                await lib_download.start_download_flow(msg, user.id, kind, query)
                return

            rintent = steam_flow.detect_review_intent(text)
            if rintent:
                await repo.add_message(s, user.id, "user", text)
                await steam_flow.start_review_flow(msg, user.id, rintent)
                return

        try:
            action = "upload_photo" if images else "typing"
            if settings.TYPING_INDICATOR:
                async with ChatActionSender(bot=msg.bot, chat_id=msg.chat.id, action=action):
                    result = await _core.respond(
                        s, Turn(user_id=user.id, text=text, images=images or None)
                    )
            else:
                result = await _core.respond(
                    s, Turn(user_id=user.id, text=text, images=images or None)
                )
            answer = result.text
            tools_used = result.tools
            attachments = result.attachments
        except Exception as e:
            log.exception("core error")
            err_txt = str(e)
            if "g4f:" in err_txt or "не нашла ни одного рабочего бэкенда" in err_txt:
                await _send_g4f_setup_prompt(msg, err_txt, user_id=msg.from_user.id)
            else:
                await msg.answer("Ой, меня немного закоротило \U0001f605 Попробуй ещё раз?")
            return

    if getattr(result, "ignored", False):
        log.info("\U0001f64a молчу (режим обиды) - ответа не отправляю")
        return

    kb = _tools_keyboard(tools_used) if (settings.SHOW_TOOL_CALLS and tools_used) else None
    force_voice = _wants_voice(text)
    await send_humanlike(msg, answer, reply_markup=kb,
                         disable_web_page_preview=False, mood=cur_mood,
                         force_voice=force_voice)
    if attachments:
        await _send_attachments(msg, attachments)

    # Явная просьба прислать стикер — гарантированно отправляем (с фоллбэком на эмодзи)
    if _wants_sticker(text):
        try:
            from utils import stickers as _stpk
            await _stpk.send(msg, cur_mood)
        except Exception:
            log.exception("forced sticker send failed")

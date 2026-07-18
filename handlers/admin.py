from __future__ import annotations
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import settings

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

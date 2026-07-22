"""Точка входа: инициализация бота, роутеров, БД и планировщика, запуск polling."""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

try:
    from rich.traceback import install as _rich_tb
    _rich_tb(show_locals=False, width=120, max_frames=15, word_wrap=True,
             suppress=["aiogram", "asyncio", "httpx", "anyio", "g4f"])
except Exception:
    pass

def _first_run_check() -> None:
    env = ROOT / ".env"
    need_wizard = False
    if not env.exists():
        need_wizard = True
    else:
        text = env.read_text(encoding="utf-8", errors="ignore")
        got_token = False
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("BOT_TOKEN="):
                got_token = True
                if not s.split("=", 1)[1].strip():
                    need_wizard = True
                break
        if not got_token:
            need_wizard = True

    if not need_wizard:
        return

    print(
        "\nMahiru ещё не настроена.\n"
        "Запусти мастер первой настройки отдельной командой:\n\n"
        "    python setup_wizard.py\n",
        flush=True,
    )
    sys.exit(0)

_first_run_check()

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from aiogram.types import ErrorEvent
from aiogram.exceptions import TelegramNetworkError

from aiogram.types import BotCommand, BotCommandScopeDefault

from config import settings
from utils.logger import setup_logger, log
from utils.settings_kv import load_overrides, load_behavior_overrides
from db.session import init_db
from handlers import messages, admin, callbacks, lib_download, steam_flow
from scheduler.autonomous import AutonomousScheduler

BOT_COMMANDS = [
    BotCommand(command="start",    description="🌸 Привет / начать общение"),
    BotCommand(command="admin",    description="⚙️ Панель настроек"),
    BotCommand(command="human",    description="🎭 Очеловечивание (печатает, паузы)"),
    BotCommand(command="humanset", description="🎛 Тонкая настройка поведения"),
    BotCommand(command="date",     description="📅 Памятные даты (поздравляет сама)"),
    BotCommand(command="screen",   description="👀 Смотрит на экран и комментирует"),
    BotCommand(command="sticker",  description="🏷 Стикеры / кастом-эмодзи"),
    BotCommand(command="set",      description="🌺 Изменить личность"),
    BotCommand(command="keys",     description="🔐 API-ключи провайдеров"),
    BotCommand(command="setkey",   description="🗝 Сохранить ключ/токен"),
]

async def _setup_bot_commands(bot: "Bot") -> None:
    """Регистрирует команды в меню Telegram, чтоб они были под кнопкой Menu."""
    try:
        await bot.set_my_commands(BOT_COMMANDS, scope=BotCommandScopeDefault())
        log.info(f"📋 зарегистрировано {len(BOT_COMMANDS)} команд в меню Telegram")
    except Exception:
        log.exception("set_my_commands failed")

async def main() -> None:
    setup_logger(settings.LOG_LEVEL)
    log.info("Mahiru запускается…")

    await init_db()

    try:
        n = await load_overrides()
        if n:
            log.info(f"🔐 подгружено {n} API-ключей из БД")
    except Exception:
        log.exception("load_overrides failed")

    try:
        nb = await load_behavior_overrides()
        if nb:
            log.info(f"🎭 подгружено {nb} настроек очеловечивания из БД")
    except Exception:
        log.exception("load_behavior_overrides failed")

    import time as _time
    _net_noise = {"last": 0.0, "suppressed": 0}
    def _loop_exc_handler(loop, context):
        exc = context.get("exception")
        if isinstance(exc, (TelegramNetworkError, OSError, ConnectionError)):
            now_ts = _time.monotonic()
            if now_ts - _net_noise["last"] >= 120:
                extra = (f" (+{_net_noise['suppressed']} похожих скрыто)"
                         if _net_noise["suppressed"] else "")
                log.warning(f"сеть Telegram подтормозила (фон, транзиентно){extra}: {exc}")
                _net_noise["last"] = now_ts
                _net_noise["suppressed"] = 0
            else:
                _net_noise["suppressed"] += 1
            return
        loop.default_exception_handler(context)
    try:
        asyncio.get_running_loop().set_exception_handler(_loop_exc_handler)
    except Exception:
        pass

    if settings.TELEGRAM_PROXY:
        session = AiohttpSession(proxy=settings.TELEGRAM_PROXY)
        log.info(f"🌐 Telegram через прокси: {settings.TELEGRAM_PROXY}")
    else:
        session = AiohttpSession()
    try:
        session.timeout = settings.TELEGRAM_TIMEOUT
    except Exception:
        pass

    bot = Bot(
        token=settings.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.include_router(admin.router)
    dp.include_router(callbacks.router)
    dp.include_router(lib_download.router)
    dp.include_router(steam_flow.router)
    dp.include_router(messages.router)

    @dp.errors()
    async def _on_error(event: ErrorEvent) -> bool:
        if isinstance(event.exception, TelegramNetworkError):
            log.warning(f"сеть Telegram подтормозила: {event.exception}")
            return True
        log.exception("необработанная ошибка в хендлере", exc_info=event.exception)
        return True

    if settings.DEFAULT_PROVIDER.lower() == "ollama":
        async def _prewarm_ollama() -> None:
            try:
                from ai.providers import ollama_bootstrap
                log.info("🔄 готовлю Ollama в фоне…")
                await ollama_bootstrap.ensure_ollama_ready(
                    settings.OLLAMA_HOST, settings.OLLAMA_MODEL
                )
                log.info("✅ Ollama готова к работе")
            except Exception:
                log.exception("авто-поднятие Ollama не удалось (попробую при первом сообщении)")
        asyncio.create_task(_prewarm_ollama())

    scheduler = AutonomousScheduler(bot)
    if settings.AUTONOMOUS_ENABLED:
        scheduler.start()

    try:
        me = await bot.get_me()
        log.info(f"Подключена как @{me.username}")
        await _setup_bot_commands(bot)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass

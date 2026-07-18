from __future__ import annotations
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

try:
    # красивые трейсы если либа есть
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
from aiogram.enums import ParseMode

from aiogram.types import ErrorEvent
from aiogram.exceptions import TelegramNetworkError

from config import settings
from utils.logger import setup_logger, log
from utils.settings_kv import load_overrides
from db.session import init_db
from handlers import messages, admin, callbacks, lib_download, steam_flow
from scheduler.autonomous import AutonomousScheduler

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

    bot = Bot(
        token=settings.BOT_TOKEN,
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

    scheduler = AutonomousScheduler(bot)
    if settings.AUTONOMOUS_ENABLED:
        scheduler.start()

    try:
        me = await bot.get_me()
        log.info(f"Подключена как @{me.username}")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass

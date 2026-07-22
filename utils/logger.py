"""Настройка логирования loguru."""
from __future__ import annotations
import sys
from loguru import logger as log

_configured = False

def _install_rich_tb() -> None:
    try:
        from rich.traceback import install as _install
        _install(
            show_locals=False,
            width=120,
            max_frames=15,
            word_wrap=True,
            suppress=["aiogram", "asyncio", "httpx", "anyio", "g4f"],
        )
    except Exception:
        pass

def setup_logger(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    _configured = True

    _install_rich_tb()

    log.remove()

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    fmt = (
        "<magenta>🌸</magenta> "
        "<green>{time:HH:mm:ss}</green> "
        "<lvl>{level.icon} {level:<7}</lvl> "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> "
        "<lvl>{message}</lvl>"
    )

    log.add(
        sys.stdout,
        level=level,
        colorize=True,
        format=fmt,
        backtrace=True,
        diagnose=False,
    )

    log.add(
        "mahiru.log",
        level=level,
        rotation="5 MB",
        retention="14 days",
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
    )

    try:
        log.level("DEBUG",   icon="ℹ️", color="<blue>")
        log.level("INFO",    icon="💬", color="<white>")
        log.level("SUCCESS", icon="✨", color="<green>")
        log.level("WARNING", icon="⚠️ ", color="<yellow>")
        log.level("ERROR",   icon="💥", color="<red>")
        log.level("CRITICAL", icon="🔥", color="<red><bold>")
    except Exception:
        pass

__all__ = ["log", "setup_logger"]

"""Захват экрана владельца для «живого» комментария Махиру.

Работает на той машине, где ЗАПУЩЕН бот (обычно это твой ПК): бот видит
именно этот экран. Делает скриншот, ужимает его и отдаёт JPEG-байты,
которые уходят в vision-модель. Если графической среды нет (сервер без
монитора) или нет прав - вернёт None, и фича просто молча выключится.

Захват пробуем в порядке: mss (кроссплатформенно) -> PIL ImageGrab
(Windows/macOS). Нужен установленный Pillow (он уже в requirements).
"""
from __future__ import annotations
import io

from config import settings
from utils.logger import log


def _capture_raw(monitor_index: int):
    """Снимает экран и возвращает PIL.Image (RGB) или None."""
    # 1) mss - Windows / macOS / Linux (X11)
    try:
        import mss  # type: ignore
        from PIL import Image
        with mss.mss() as sct:
            monitors = sct.monitors  # [0] = все мониторы вместе, [1..] = по одному
            idx = monitor_index
            if idx < 0 or idx >= len(monitors):
                idx = 0
            shot = sct.grab(monitors[idx])
            return Image.frombytes("RGB", shot.size, shot.rgb)
    except Exception as e:
        log.debug(f"screen: mss не сработал ({e}), пробую PIL ImageGrab")

    # 2) PIL ImageGrab - Windows / macOS
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        return img.convert("RGB")
    except Exception as e:
        log.debug(f"screen: PIL ImageGrab не сработал ({e})")

    return None


def capture_screen_jpeg() -> bytes | None:
    """Скриншот -> ужатый JPEG (bytes) или None, если экран недоступен."""
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        log.warning("screen: Pillow не установлен - захват экрана недоступен")
        return None

    monitor_index = int(getattr(settings, "SCREEN_WATCH_MONITOR", 0) or 0)
    max_width = int(getattr(settings, "SCREEN_WATCH_MAX_WIDTH", 1280) or 1280)
    quality = int(getattr(settings, "SCREEN_WATCH_JPEG_QUALITY", 70) or 70)

    img = _capture_raw(monitor_index)
    if img is None:
        return None
    try:
        if max_width and img.width > max_width:
            new_h = max(1, int(img.height * (max_width / img.width)))
            img = img.resize((max_width, new_h))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=max(30, min(95, quality)))
        return buf.getvalue()
    except Exception:
        log.exception("screen: не смогла ужать скриншот")
        return None


def screen_available() -> bool:
    """Быстрая проверка (для мастера настройки): получится ли снять экран."""
    try:
        return capture_screen_jpeg() is not None
    except Exception:
        return False

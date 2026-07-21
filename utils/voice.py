"""Голосовые ответы Mahiru через локальный Silero TTS.

Бесплатно, без API-ключа, работает offline (модель скачается один раз).

Чтобы включить (тяжёлые зависимости ставятся отдельно, чтобы не раздувать основную сборку):
    pip install torch
    # и установи ffmpeg в системе (нужен для ogg/opus - формата голосовых Telegram)
    # затем в .env: VOICE_ENABLED=true

Всё best-effort: если torch/ffmpeg нет или синтез упал - функция вернёт None,
и бот просто ответит текстом. Ничего не ломается.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import threading

from config import settings
from utils.logger import log

_model = None
_load_failed = False
_load_lock = threading.Lock()
_SAMPLE_RATE = 48000

_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+")
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "\U00002190-\U000021FF"
    "\uFE0F"
    "]",
    flags=re.UNICODE,
)


def _clean_for_tts(text: str) -> str:
    if not text:
        return ""
    t = _TAG_RE.sub(" ", text)
    t = _URL_RE.sub(" ", t)
    t = _EMOJI_RE.sub(" ", t)
    for ch in ("*", "_", "`", "#", ">", "|"):
        t = t.replace(ch, "")
    t = re.sub(r"\s+", " ", t).strip()
    return t


_ffmpeg_cache: str | None = None
_ffmpeg_resolved = False


def _resolve_ffmpeg() -> str | None:
    """Ищет ffmpeg: env/настройка FFMPEG_BINARY, PATH, типичные места установки на Windows."""
    global _ffmpeg_cache, _ffmpeg_resolved
    if _ffmpeg_resolved:
        return _ffmpeg_cache

    candidates: list[str] = []
    for env_key in ("FFMPEG_BINARY", "IMAGEIO_FFMPEG_EXE", "FFMPEG_PATH"):
        v = os.environ.get(env_key)
        if v:
            candidates.append(v)
    cfg = getattr(settings, "FFMPEG_BINARY", "") or ""
    if cfg:
        candidates.append(cfg)
    candidates += ["ffmpeg", "ffmpeg.exe"]

    resolved: str | None = None
    for c in candidates:
        if os.path.isabs(c) and os.path.isfile(c):
            resolved = c
            break
        found = shutil.which(c)
        if found:
            resolved = found
            break

    if resolved is None and os.name == "nt":
        import glob
        globs = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\**\ffmpeg.exe"),
            os.path.expandvars(r"%USERPROFILE%\**\ffmpeg*\bin\ffmpeg.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\**\ffmpeg*\bin\ffmpeg.exe"),
        ]
        for pat in globs:
            try:
                hits = glob.glob(pat, recursive=True)
            except Exception:
                hits = []
            if hits:
                resolved = hits[0]
                break

    _ffmpeg_cache = resolved
    _ffmpeg_resolved = True
    if resolved:
        log.info("🎙 ffmpeg найден: {}", resolved)
    return resolved


def _have_ffmpeg() -> bool:
    return _resolve_ffmpeg() is not None


def _pip_install(args: list[str]) -> bool:
    import subprocess
    import sys
    try:
        log.info("🎙 ставлю зависимости для голоса: {} (разово, может занять пару минут)", " ".join(args))
        subprocess.run([sys.executable, "-m", "pip", "install", *args],
                       check=True, timeout=2400)
        return True
    except Exception as e:
        log.warning("🎙 не смогла установить {} ({})", args, e)
        return False


def _ensure_module(mod: str, pip_name: str | None = None) -> bool:
    """Импортирует модуль; если его нет и разрешено - доустанавливает через pip."""
    import importlib
    try:
        importlib.import_module(mod)
        return True
    except Exception:
        pass
    if not getattr(settings, "VOICE_AUTO_INSTALL", True):
        return False
    ok = _pip_install([pip_name or mod])
    importlib.invalidate_caches()
    return ok


def _ensure_torch() -> bool:
    """Проверяет torch; если его нет и разрешено - ставит сама (CPU-сборка) + зависимости Silero."""
    have_torch = False
    try:
        import torch
        have_torch = True
    except Exception:
        pass
    if not have_torch:
        if not getattr(settings, "VOICE_AUTO_INSTALL", True):
            log.warning("🎙 torch не установлен, а автоустановка выключена (VOICE_AUTO_INSTALL=false)")
            return False
        idx = (getattr(settings, "VOICE_TORCH_INDEX_URL", "") or "").strip()
        torch_args = ["torch"] + (["--index-url", idx] if idx else [])
        log.info("🎙 torch не найден - ставлю автоматически (CPU-сборка, ~200 МБ)")
        if not _pip_install(torch_args):
            return False
    for dep in ("numpy", "omegaconf"):
        _ensure_module(dep)
    try:
        import importlib
        importlib.invalidate_caches()
        import torch
        log.info("🎙 torch готов")
        return True
    except Exception as e:
        log.warning("🎙 torch поставился, но не импортируется ({}) - возможно, нужен перезапуск бота", e)
        return False


def _hub_load(pack: str):
    import torch
    kwargs = dict(repo_or_dir="snakers4/silero-models", model="silero_tts",
                  language="ru", speaker=pack)
    try:
        return torch.hub.load(trust_repo=True, **kwargs)
    except TypeError:
        return torch.hub.load(**kwargs)


def _load_model():
    """Ленивая загрузка Silero (один раз). При ошибке - больше не пытаемся."""
    global _model, _load_failed
    if _model is not None or _load_failed:
        return _model
    with _load_lock:
        if _model is not None or _load_failed:
            return _model
        if not _ensure_torch():
            _load_failed = True
            return _model
        try:
            import torch
            import importlib
            pack = getattr(settings, "VOICE_MODEL_ID", "v4_ru")
            log.info("🎙 загружаю модель Silero TTS ({}) - при первом запуске скачается (~50 МБ)", pack)
            model = None
            last_err = None
            for _attempt in range(5):
                try:
                    model, _ = _hub_load(pack)
                    last_err = None
                    break
                except ModuleNotFoundError as e:
                    last_err = e
                    name = getattr(e, "name", None)
                    if not name or not getattr(settings, "VOICE_AUTO_INSTALL", True):
                        break
                    log.info("🎙 Silero требует модуль {} - доустанавливаю", name)
                    if not _pip_install([name]):
                        break
                    importlib.invalidate_caches()
            if model is None:
                raise last_err or RuntimeError("не удалось загрузить модель")
            try:
                model.to(torch.device("cpu"))
            except Exception:
                pass
            _model = model
            log.info("🎙 Silero TTS загружен (пакет {})", pack)
        except Exception as e:
            _load_failed = True
            log.warning("🎙 не удалось загрузить Silero TTS ({}) - озвучка отключена", e)
        return _model


def _render(model, text: str) -> str | None:
    """Синтез -> wav -> ogg/opus. Блокирующий, запускать в потоке."""
    import wave
    import subprocess
    import numpy as np

    speaker = getattr(settings, "VOICE_SPEAKER", "xenia")
    sr = _SAMPLE_RATE
    try:
        audio = model.apply_tts(text=text, speaker=speaker, sample_rate=sr,
                                put_accent=True, put_yo=True)
    except TypeError:
        audio = model.apply_tts(text=text, speaker=speaker, sample_rate=sr)
    try:
        data = audio.numpy()
    except Exception:
        data = np.array(audio)
    pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2")

    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())

    ogg_path = wav_path[:-4] + ".ogg"
    exe = _resolve_ffmpeg() or "ffmpeg"
    cmd = [exe, "-y", "-loglevel", "error", "-i", wav_path,
           "-c:a", "libopus", "-b:a", "32k", ogg_path]
    try:
        subprocess.run(cmd, check=True, timeout=60)
    finally:
        try:
            os.remove(wav_path)
        except Exception:
            pass

    if not os.path.exists(ogg_path) or os.path.getsize(ogg_path) == 0:
        try:
            os.remove(ogg_path)
        except Exception:
            pass
        return None
    return ogg_path


async def synthesize(text: str, force: bool = False) -> str | None:
    """Озвучить текст. force=True - по явной просьбе (в обход VOICE_ENABLED и лимита длины)."""
    if not force and not getattr(settings, "VOICE_ENABLED", False):
        return None
    clean = _clean_for_tts(text)
    if not clean:
        return None
    if not force and len(clean) > int(getattr(settings, "VOICE_MAX_CHARS", 200)):
        return None
    if not _have_ffmpeg():
        log.warning("🎙 ffmpeg не найден в PATH этого процесса - перезапусти бота из нового терминала или задай FFMPEG_BINARY в .env")
        return None
    model = await asyncio.to_thread(_load_model)
    if model is None:
        return None
    try:
        return await asyncio.to_thread(_render, model, clean)
    except Exception as e:
        log.warning("🎙 синтез речи упал ({}) - отвечу текстом", e)
        return None

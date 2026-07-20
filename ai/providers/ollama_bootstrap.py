"""
Авто-поднятие Ollama.

Цель: юзеру не надо делать РОВНО НИЧЕГО. При первом запросе к Ollama мы:
  1) проверяем, жив ли сервер (GET /api/tags);
  2) если нет — ищем бинарник ollama, а если его нет — СКАЧИВАЕМ и СТАВИМ его;
  3) запускаем `ollama serve` в фоне и ждём пока поднимется;
  4) проверяем есть ли модель, если нет — `pull`-им её (с логами прогресса).

Всё идемпотентно и под одним асинхронным локом, чтобы параллельные сообщения не дёргали установку дважды.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import httpx

from utils.logger import log

try:
    from config import settings
except Exception:  # на всякий случай, чтоб модуль не ломался при импорте
    settings = None  # type: ignore

_WIN_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
_MAC_ZIP_URL = "https://ollama.com/download/Ollama-darwin.zip"
_LINUX_INSTALL_SH = "https://ollama.com/install.sh"

_lock = asyncio.Lock()
_ready: set[tuple[str, str]] = set()   # (host, model) уже готовы
_server_ok: set[str] = set()           # host, на котором сервер точно поднят


def _opt(name: str, default: bool = True) -> bool:
    if settings is None:
        return default
    return bool(getattr(settings, name, default))


def _is_local(host: str) -> bool:
    h = host.lower()
    return "localhost" in h or "127.0.0.1" in h or "0.0.0.0" in h or "::1" in h


def invalidate(host: str, model: str | None = None) -> None:
    """Сбросить кеш готовности (например, когда chat всё равно получил 404)."""
    _server_ok.discard(host)
    if model is None:
        for key in list(_ready):
            if key[0] == host:
                _ready.discard(key)
    else:
        _ready.discard((host, model))


# ---------------------------------------------------------------- сеть ----
async def _server_alive(host: str, timeout: float = 2.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(f"{host}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def _model_present(host: str, model: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{host}/api/tags")
            r.raise_for_status()
            data = r.json()
    except Exception:
        return False
    names = {m.get("name", "") for m in (data.get("models") or [])}
    names |= {n.split(":", 1)[0] for n in names}   # без тега
    want = model
    want_base = model.split(":", 1)[0]
    return want in names or want_base in names or f"{want_base}:latest" in names


# ---------------------------------------------------- поиск бинарника ----
def _find_binary() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    sysname = platform.system()
    cands: list[Path] = []
    if sysname == "Windows":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            cands.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        cands.append(Path(pf) / "Ollama" / "ollama.exe")
    elif sysname == "Darwin":
        cands += [Path("/usr/local/bin/ollama"),
                  Path("/opt/homebrew/bin/ollama"),
                  Path("/Applications/Ollama.app/Contents/Resources/ollama")]
    else:
        cands += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama"),
                  Path.home() / ".ollama" / "bin" / "ollama"]
    for c in cands:
        try:
            if c.exists():
                return str(c)
        except Exception:
            pass
    return None


# ------------------------------------------------------------- установка ----
def _download(url: str, dest: Path) -> None:
    log.info(f"⬇️  скачиваю {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mahiru-bot"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def _install_windows() -> str | None:
    tmp = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
    try:
        _download(_WIN_INSTALLER_URL, tmp)
    except Exception:
        log.exception("не смогла скачать установщик Ollama")
        return None
    # Inno Setup: тихая установка без окон
    log.info("⚙️  ставлю Ollama (тихо)…")
    for args in (
        ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        ["/SILENT"],
        [],
    ):
        try:
            subprocess.run([str(tmp), *args], check=False, timeout=600)
        except Exception:
            continue
        b = _find_binary()
        if b:
            return b
    return _find_binary()


def _install_macos() -> str | None:
    # сначала brew, если есть
    if shutil.which("brew"):
        try:
            log.info("⚙️  ставлю Ollama через brew…")
            subprocess.run(["brew", "install", "ollama"], check=False, timeout=900)
            b = _find_binary()
            if b:
                return b
        except Exception:
            pass
    # иначе качаем .zip и кладём Ollama.app в /Applications
    tmp = Path(tempfile.gettempdir()) / "Ollama-darwin.zip"
    try:
        _download(_MAC_ZIP_URL, tmp)
        with zipfile.ZipFile(tmp) as z:
            z.extractall("/Applications")
    except Exception:
        log.exception("не смогла установить Ollama на macOS")
    return _find_binary()


def _install_linux() -> str | None:
    try:
        log.info("⚙️  ставлю Ollama через официальный install.sh…")
        subprocess.run(f"curl -fsSL {_LINUX_INSTALL_SH} | sh",
                       shell=True, check=False, timeout=900)
    except Exception:
        log.exception("не смогла установить Ollama на Linux")
    return _find_binary()


def _install() -> str | None:
    sysname = platform.system()
    if sysname == "Windows":
        return _install_windows()
    if sysname == "Darwin":
        return _install_macos()
    return _install_linux()


def _start_server(exe: str) -> None:
    log.info("▶️  запускаю `ollama serve` в фоне…")
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    try:
        if platform.system() == "Windows":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | \
                    getattr(subprocess, "DETACHED_PROCESS", 0)
            kwargs["creationflags"] = flags
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([exe, "serve"], **kwargs)
    except Exception:
        # возможно сервер уже запущен (tray-приложение) — это ок
        log.debug("ollama serve не стартовал (вероятно уже работает)")


# ------------------------------------------------------------- pull модели ----
def _fmt_bytes(n: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024 or unit == "ТБ":
            return f"{n:.1f} {unit}" if unit != "Б" else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


def _bar(frac: float, width: int = 24) -> str:
    frac = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
    filled = int(round(frac * width))
    return "█" * filled + "░" * (width - filled)


async def _pull_model(host: str, model: str) -> None:
    log.info(f"⬇️  тяну модель Ollama: {model} (может занять несколько минут)…")
    import time as _time

    last_status = ""
    last_log_ts = 0.0
    last_completed = 0
    last_speed_ts = 0.0
    speed = 0.0  # байт/сек
    cur_digest = ""

    async with httpx.AsyncClient(timeout=None) as c:
        async with c.stream("POST", f"{host}/api/pull",
                            json={"model": model, "stream": True}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("error"):
                    raise RuntimeError(f"ollama pull error: {d['error']}")

                status = d.get("status", "")
                total = d.get("total") or 0
                completed = d.get("completed") or 0
                digest = d.get("digest") or ""
                now = _time.monotonic()

                # новый слой — сбрасываем счётчик скорости
                if digest and digest != cur_digest:
                    cur_digest = digest
                    last_completed = 0
                    last_speed_ts = now

                # оценка скорости скачивания
                if completed and last_speed_ts and now - last_speed_ts >= 0.5:
                    delta = completed - last_completed
                    dt = now - last_speed_ts
                    if delta > 0 and dt > 0:
                        speed = delta / dt
                    last_completed = completed
                    last_speed_ts = now

                # слой с известным размером — рисуем прогресс-бар
                if total > 0:
                    frac = completed / total
                    # логаем не чаще раза в секунду (или когда дошли до 100%)
                    if now - last_log_ts >= 1.0 or frac >= 1.0:
                        last_log_ts = now
                        eta = ""
                        if speed > 0 and total > completed:
                            secs = int((total - completed) / speed)
                            eta = f" ~{secs // 60}м{secs % 60:02d}с" if secs >= 60 else f" ~{secs}с"
                        spd = f" {_fmt_bytes(speed)}/с" if speed > 0 else ""
                        log.info(
                            f"   [{_bar(frac)}] {frac * 100:5.1f}%  "
                            f"{_fmt_bytes(completed)} / {_fmt_bytes(total)}{spd}{eta}"
                        )
                # служебные статусы без размера (manifest, verifying, и т.д.)
                elif status and status != last_status:
                    log.info(f"   ollama pull: {status}")

                if status:
                    last_status = status
    log.info(f"✅ модель {model} скачана и готова")


# ---------------------------------------------------------------- главное ----
async def _ensure_server(host: str) -> None:
    if host in _server_ok and await _server_alive(host):
        return
    if await _server_alive(host):
        _server_ok.add(host)
        return

    if not _is_local(host):
        raise RuntimeError(
            f"Ollama недоступна по {host}, а автоустановка работает только для localhost."
        )

    exe = _find_binary()
    if not exe and _opt("OLLAMA_AUTO_INSTALL"):
        log.warning("Ollama не найдена — скачиваю и ставлю автоматически…")
        exe = await asyncio.to_thread(_install)
    if not exe:
        raise RuntimeError(
            "Не удалось найти/установить Ollama автоматически. "
            "Поставь вручную с https://ollama.com/download"
        )

    if _opt("OLLAMA_AUTO_START"):
        await asyncio.to_thread(_start_server, exe)

    for _ in range(90):  # до ~90 секунд на подъём
        if await _server_alive(host):
            _server_ok.add(host)
            log.info("✅ Ollama сервер поднят")
            return
        await asyncio.sleep(1)
    raise RuntimeError("Ollama сервер не поднялся за отведённое время.")


async def ensure_ollama_ready(host: str, model: str) -> None:
    """Гарантирует: сервер жив и модель скачана. Идемпотентно."""
    host = host.rstrip("/")
    if (host, model) in _ready and host in _server_ok:
        return
    async with _lock:
        if (host, model) in _ready and host in _server_ok:
            return
        await _ensure_server(host)
        if not await _model_present(host, model):
            if _opt("OLLAMA_AUTO_PULL"):
                await _pull_model(host, model)
            else:
                raise RuntimeError(f"Модель Ollama '{model}' не скачана.")
        _ready.add((host, model))

from __future__ import annotations
import asyncio
import re
import time
from typing import Any

import httpx
import requests

from utils.logger import log
from utils.settings_kv import get_key

API_BASE = "https://api.cdnlibs.org"

SITE_ID = {"manga": 1, "ranobe": 3, "hentai": 4}
REFERER = {
    "manga":  "https://mangalib.org/",
    "ranobe": "https://ranobelib.me/",
    "hentai": "https://hentailib.me/",
}
TOKEN_KEY = {
    "manga":  "MANGALIB_TOKEN",
    "ranobe": "RANOBELIB_TOKEN",
    "hentai": "HENTAILIB_TOKEN",
}

IMG_SERVERS = [
    "https://img3.cdnlibs.org",
    "https://img2.cdnlibs.org",
    "https://img4.cdnlibs.org",
    "https://img.cdnlibs.org",
]

IMAGE_REFERER = "https://mangalib.org/"

async def image_servers(kind: str) -> list[str]:
    return list(IMG_SERVERS)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

class LibError(RuntimeError):
    pass

async def _headers(kind: str) -> dict[str, str]:
    if kind not in SITE_ID:
        raise LibError(f"unknown kind {kind!r}, expected one of {list(SITE_ID)}")
    h = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru,en;q=0.9",
        "Origin": REFERER[kind].rstrip("/"),
        "Referer": REFERER[kind],
        "Site-Id": str(SITE_ID[kind]),
    }
    tok = await get_key(TOKEN_KEY[kind], default="") or await get_key("LIB_TOKEN", default="")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h

async def api_get(kind: str, path: str, params: dict[str, Any] | None = None,
                  timeout: float = 20.0) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    hdrs = await _headers(kind)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
        try:
            r = await c.get(url, params=params, headers=hdrs)
        except httpx.HTTPError as e:
            raise LibError(f"HTTP {kind} {path}: {e}") from e
    if r.status_code == 401:
        raise LibError(
            f"{kind}: требуется авторизация (401). Введи общий токен через "
            f"/setkey LIB_TOKEN <token>. Взять токен: открой "
            f"{REFERER[kind]} в браузере с DevTools -> Application -> "
            f"Local Storage -> auth. Скопируй значение поля token."
        )
    if r.status_code >= 500:
        raise LibError(f"{kind}: сервер {r.status_code}")
    if r.status_code >= 400:
        raise LibError(f"{kind}: {r.status_code} {r.text[:200]}")
    try:
        return r.json()
    except Exception as e:
        raise LibError(f"{kind}: bad json — {e}: {r.text[:200]}") from e

def _rel_path(url: str) -> str | None:
    m = re.match(r"^https?://[^/]+(/.*)$", url)
    if m:
        return m.group(1)
    if url.startswith("/"):
        return url
    return None

def _img_path(raw: str) -> str:
    raw = (raw or "").strip()
    m = re.match(r"^https?://[^/]+(/.*)$", raw)
    if m:
        return m.group(1)
    if raw.startswith("//"):
        return raw[1:]
    if not raw.startswith("/"):
        return "/" + raw
    return raw

def _download_image_sync(candidates: list[str], timeout: float) -> bytes:
    hdrs = {
        "User-Agent": UA,
        "Referer": IMAGE_REFERER,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    last_err: str | None = None
    for u in candidates:
        try:
            r = requests.get(u, headers=hdrs, timeout=timeout, stream=True)
            if r.status_code == 200:
                content = r.content
                if content:
                    return content
            last_err = f"{r.status_code} @ {u}"
        except requests.RequestException as e:
            last_err = f"{type(e).__name__} @ {u}"
    raise LibError(f"image download failed: {last_err}")

async def download_image(url: str, timeout: float = 30.0,
                         servers: list[str] | None = None) -> bytes:
    path = _img_path(url)

    bases: list[str] = []
    for b in (servers or []):
        b = b.rstrip("/")
        if b and b not in bases:
            bases.append(b)
    for b in IMG_SERVERS:
        b = b.rstrip("/")
        if b not in bases:
            bases.append(b)

    candidates = [base + path for base in bases]
    try:
        return await asyncio.to_thread(_download_image_sync, candidates, timeout)
    except LibError as e:
        raise LibError(f"{e} (путь {path}, хосты: {', '.join(bases)})") from e

def _download_bytes_sync(url: str, timeout: float, referer: str) -> bytes:
    hdrs = {
        "User-Agent": UA,
        "Referer": referer,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    r = requests.get(url, headers=hdrs, timeout=timeout, stream=True)
    if r.status_code == 200 and r.content:
        return r.content
    raise LibError(f"download failed: {r.status_code} @ {url}")

async def download_bytes(url: str, timeout: float = 30.0,
                         referer: str = IMAGE_REFERER) -> bytes:
    url = (url or "").strip()
    if not url:
        raise LibError("пустой url")
    if url.startswith("//"):
        url = "https:" + url
    return await asyncio.to_thread(_download_bytes_sync, url, timeout, referer)

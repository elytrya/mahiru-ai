"""Простой in-memory кэш с TTL."""
from __future__ import annotations
import asyncio
import json
import time
from typing import Any

from config import settings
from utils.logger import log

_pool = None
_backend: str = "unknown"
_mem: dict[str, tuple[float, str]] = {}
_mem_lock = asyncio.Lock()

async def _init_backend() -> None:
    global _pool, _backend
    if _backend != "unknown":
        return
    url = (settings.REDIS_URL or "").strip()
    if not url:
        _backend = "memory"
        return
    try:
        import redis.asyncio as redis
        _pool = redis.from_url(url, decode_responses=True,
                                socket_connect_timeout=1.5)
        await asyncio.wait_for(_pool.ping(), timeout=1.5)
        _backend = "redis"
        log.info("cache: Redis подключён")
    except Exception as e:
        _pool = None
        _backend = "memory"
        log.warning(f"cache: Redis недоступен ({type(e).__name__}), в памяти")

async def _mem_gc() -> None:
    now = time.time()
    dead = [k for k, (exp, _) in _mem.items() if exp and exp < now]
    for k in dead:
        _mem.pop(k, None)

async def cache_get(key: str) -> Any | None:
    await _init_backend()
    if _backend == "redis" and _pool is not None:
        try:
            raw = await _pool.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None
    async with _mem_lock:
        await _mem_gc()
        v = _mem.get(key)
        if not v:
            return None
        exp, raw = v
        if exp and exp < time.time():
            _mem.pop(key, None)
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    await _init_backend()
    if _backend == "redis" and _pool is not None:
        try:
            await _pool.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
            return
        except Exception:
            pass
    async with _mem_lock:
        _mem[key] = (time.time() + ttl if ttl else 0.0,
                     json.dumps(value, ensure_ascii=False, default=str))
        if len(_mem) > 2000:
            await _mem_gc()

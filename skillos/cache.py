from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Protocol


class CacheBackend(Protocol):
    def get(self, key: str) -> str | None:
        ...

    def set(self, key: str, value: str, ttl_seconds: int | None) -> None:
        ...


@dataclass(frozen=True)
class CacheConfig:
    enabled: bool = False
    ttl_seconds: int = 60
    prefix: str = "skillos"
    redis_url: str | None = None


class MemoryCache:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[str, float | None]] = {}

    def get(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if not entry:
            return None
        value, expires_at = entry
        if expires_at is not None and time.monotonic() >= expires_at:
            self._entries.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl_seconds: int | None) -> None:
        expires_at = (
            time.monotonic() + ttl_seconds if ttl_seconds is not None else None
        )
        self._entries[key] = (value, expires_at)


class RedisCache:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url)

    def get(self, key: str) -> str | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return str(raw)

    def set(self, key: str, value: str, ttl_seconds: int | None) -> None:
        if ttl_seconds is None:
            self._client.set(key, value)
            return
        self._client.setex(key, ttl_seconds, value)


def cache_config_from_env() -> CacheConfig:
    enabled = _env_bool("SKILLOS_CACHE_ENABLED", False)
    ttl_seconds = _env_int("SKILLOS_CACHE_TTL_SECONDS", 60)
    prefix = os.getenv("SKILLOS_CACHE_PREFIX", "skillos").strip() or "skillos"
    redis_url = os.getenv("SKILLOS_REDIS_URL") or os.getenv("REDIS_URL")
    return CacheConfig(
        enabled=enabled,
        ttl_seconds=ttl_seconds,
        prefix=prefix,
        redis_url=redis_url,
    )


def cache_backend_from_env(config: CacheConfig | None = None) -> CacheBackend | None:
    config = config or cache_config_from_env()
    if not config.enabled:
        return None
    if config.redis_url:
        return RedisCache(config.redis_url)
    return MemoryCache()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default

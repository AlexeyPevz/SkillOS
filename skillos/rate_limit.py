from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Protocol

from skillos.cache import CacheBackend, cache_backend_from_env


class RateLimiter(Protocol):
    def check_and_consume(self, key: str, cost: int = 1) -> bool:
        ...


@dataclass(frozen=True)
class RateLimitConfig:
    enabled: bool = True
    limit: int = 60
    window_seconds: int = 60


class NoOpRateLimiter:
    def check_and_consume(self, key: str, cost: int = 1) -> bool:
        return True


class BackendRateLimiter:
    """
    Fixed window rate limiter using CacheBackend.
    Note: Without atomic INCR in CacheBackend, this has race conditions in distributed envs.
    For strict enforcement, CacheBackend needs atomic operations.
    """

    def __init__(self, backend: CacheBackend, config: RateLimitConfig) -> None:
        self._backend = backend
        self._limit = max(1, config.limit)
        self._window = max(1, config.window_seconds)

    def check_and_consume(self, key: str, cost: int = 1) -> bool:
        current_window = int(time.time() / self._window)
        cache_key = f"ratelimit:{key}:{current_window}"
        
        # Optimistic read-modify-write...
        
        # Optimistic read-modify-write
        raw = self._backend.get(cache_key)
        current_count = int(raw) if raw else 0

        if current_count + cost > self._limit:
            return False

        # Write back (window expiration handles cleanup)
        new_count = current_count + cost
        self._backend.set(cache_key, str(new_count), self._window)
        return True


class StrictRedisRateLimiter:
    """
    Fixed window limiter backed by Redis with atomic Lua script.
    """

    _LUA = """
    local key = KEYS[1]
    local limit = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local cost = tonumber(ARGV[3])
    local current = redis.call("GET", key)
    if not current then
      redis.call("SET", key, 0, "EX", window)
      current = 0
    end
    current = tonumber(current)
    if (current + cost) > limit then
      return 0
    end
    redis.call("INCRBY", key, cost)
    redis.call("EXPIRE", key, window)
    return 1
    """

    def __init__(self, client, config: RateLimitConfig) -> None:
        self._client = client
        self._limit = max(1, config.limit)
        self._window = max(1, config.window_seconds)

    def check_and_consume(self, key: str, cost: int = 1) -> bool:
        current_window = int(time.time() / self._window)
        cache_key = f"ratelimit:{key}:{current_window}"
        result = self._client.eval(
            self._LUA,
            1,
            cache_key,
            int(self._limit),
            int(self._window),
            int(max(1, cost)),
        )
        return bool(result)


def rate_limiter_from_env() -> RateLimiter:
    enabled = _env_bool("SKILLOS_RATE_LIMIT_ENABLED", True)
    strict = _env_bool("SKILLOS_RATE_LIMIT_STRICT", False)

    limit = _env_int("SKILLOS_RATE_LIMIT_REQUESTS", 60)
    window = _env_int("SKILLOS_RATE_LIMIT_WINDOW_SECONDS", 60)
    config = RateLimitConfig(enabled=True, limit=limit, window_seconds=window)

    if strict:
        redis_url = os.getenv("SKILLOS_REDIS_URL") or os.getenv("REDIS_URL")
        if not redis_url:
            raise RuntimeError("rate_limit_strict_requires_redis")
        import redis

        client = redis.Redis.from_url(redis_url)
        return StrictRedisRateLimiter(client, config)

    if not enabled:
        return NoOpRateLimiter()

    backend = cache_backend_from_env()
    if not backend:
        # If global cache is disabled but rate limiting is enabled, use local MemoryCache
        # This ensures security even if performance caching is off.
        from skillos.cache import MemoryCache
        backend = MemoryCache()

    return BackendRateLimiter(backend, config)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default

import asyncio
import os

import asyncpg
import pytest
import redis


def _postgres_dsn() -> str:
    return os.getenv(
        "SKILLOS_POSTGRES_DSN",
        "postgresql://skillos:skillos@localhost:5432/skillos",
    )


def _redis_url() -> str:
    return os.getenv(
        "SKILLOS_REDIS_URL",
        "redis://localhost:6379/0",
    )


async def _can_connect_postgres(dsn: str) -> bool:
    try:
        connection = await asyncpg.connect(dsn=dsn, timeout=1)
    except Exception:
        return False
    await connection.execute("SELECT 1")
    await connection.close()
    return True


def _can_connect_redis(url: str) -> bool:
    try:
        client = redis.Redis.from_url(
            url,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
    except Exception:
        return False
    return True


def test_local_postgres_and_redis_available() -> None:
    postgres_ok = asyncio.run(_can_connect_postgres(_postgres_dsn()))
    if not postgres_ok:
        pytest.skip("Postgres unavailable; run docker-compose up")

    redis_ok = _can_connect_redis(_redis_url())
    if not redis_ok:
        pytest.skip("Redis unavailable; run docker-compose up")

    assert postgres_ok is True
    assert redis_ok is True

from __future__ import annotations

from dataclasses import dataclass
import shutil
from pathlib import Path
from typing import Literal

from skillos.storage_backend import storage_backend_from_env, pg_connect
from skillos.cache import cache_backend_from_env

@dataclass
class ComponentHealth:
    status: Literal["healthy", "unhealthy", "degraded"]
    details: str | None = None
    latency_ms: float | None = None

@dataclass
class SystemHealth:
    status: Literal["healthy", "unhealthy", "degraded"]
    components: dict[str, ComponentHealth]

def check_health(root_path: Path) -> SystemHealth:
    components: dict[str, ComponentHealth] = {}
    
    # 1. Disk Space
    try:
        total, used, free = shutil.disk_usage(root_path)
        # If free < 100MB, warn
        if free < 100 * 1024 * 1024:
            components["disk"] = ComponentHealth("degraded", f"Low disk space: {free} bytes")
        else:
            components["disk"] = ComponentHealth("healthy")
    except Exception as e:
        components["disk"] = ComponentHealth("unhealthy", str(e))

    # 2. Database (Postgres)
    db_config = storage_backend_from_env()
    if db_config.backend == "postgres" and db_config.postgres_dsn:
        try:
            import time
            start = time.perf_counter()
            with pg_connect(db_config.postgres_dsn) as conn:
                conn.execute("SELECT 1")
            duration = (time.perf_counter() - start) * 1000
            components["database"] = ComponentHealth("healthy", latency_ms=duration)
        except Exception as e:
            components["database"] = ComponentHealth("unhealthy", str(e))
    else:
         components["database"] = ComponentHealth("healthy", "Using SQLite/File")

    # 3. Cache (Redis)
    cache = cache_backend_from_env()
    if cache and hasattr(cache, "_client"): # RedisCache
        try:
            import time
            start = time.perf_counter()
            cache.set("__health_check__", "ok", 10)
            val = cache.get("__health_check__")
            duration = (time.perf_counter() - start) * 1000
            if val == "ok":
                components["cache"] = ComponentHealth("healthy", latency_ms=duration)
            else:
                components["cache"] = ComponentHealth("unhealthy", "Cache read mismatch")
        except Exception as e:
            components["cache"] = ComponentHealth("unhealthy", str(e))
    
    overall = "healthy"
    if any(c.status == "unhealthy" for c in components.values()):
        overall = "unhealthy"
    elif any(c.status == "degraded" for c in components.values()):
         overall = "degraded"

    return SystemHealth(status=overall, components=components)

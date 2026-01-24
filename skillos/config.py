from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True)
class AppConfig:
    env: str
    log_level: str
    postgres_dsn: str | None
    redis_url: str | None
    
    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AppConfig":
        env_map = env or os.environ
        return cls(
            env=env_map.get("SKILLOS_ENV", "dev").lower(),
            log_level=env_map.get("SKILLOS_LOG_LEVEL", "INFO").upper(),
            postgres_dsn=env_map.get("SKILLOS_POSTGRES_DSN"),
            redis_url=env_map.get("SKILLOS_REDIS_URL") or env_map.get("REDIS_URL"),
        )
    
    @property
    def is_prod(self) -> bool:
        return self.env in ("prod", "production")

def get_config() -> AppConfig:
    return AppConfig.from_env()

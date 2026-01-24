from __future__ import annotations

from dataclasses import dataclass
import os
import re
from pathlib import Path

from skillos.tenancy import tenant_id_from_path, tenant_id_from_env


_SUPPORTED_BACKENDS = {"file", "postgres"}
_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class StorageBackendConfig:
    backend: str
    postgres_dsn: str | None
    postgres_schema: str


def storage_backend_from_env() -> StorageBackendConfig:
    backend = os.getenv("SKILLOS_STORAGE_BACKEND", "file").strip().lower()
    if backend not in _SUPPORTED_BACKENDS:
        backend = "file"
    dsn = os.getenv("SKILLOS_POSTGRES_DSN") or os.getenv("DATABASE_URL")
    schema = (os.getenv("SKILLOS_POSTGRES_SCHEMA") or "skillos").strip()
    if not _SCHEMA_RE.match(schema):
        schema = "skillos"
    return StorageBackendConfig(
        backend=backend,
        postgres_dsn=dsn,
        postgres_schema=schema,
    )


def require_postgres_dsn(config: StorageBackendConfig, *, context: str) -> str:
    if not config.postgres_dsn:
        raise ValueError(f"{context}_postgres_dsn_missing")
    return config.postgres_dsn


def resolve_tenant_id(root: Path) -> str:
    return tenant_id_from_path(root) or tenant_id_from_env() or "default"


def pg_connect(dsn: str):
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(dsn, row_factory=dict_row)

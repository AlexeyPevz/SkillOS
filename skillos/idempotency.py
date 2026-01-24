from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Callable

from skillos.storage import atomic_write_text, file_lock
from skillos.tenancy import resolve_tenant_root
from skillos.storage_backend import (
    pg_connect,
    require_postgres_dsn,
    resolve_tenant_id,
    storage_backend_from_env,
)

DEFAULT_TTL_SECONDS = 300


def default_idempotency_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "runtime" / "idempotency.json"


def idempotency_ttl_from_env() -> int:
    raw = os.getenv("SKILLOS_IDEMPOTENCY_TTL_SECONDS")
    if raw is None:
        return DEFAULT_TTL_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_datetime(value: datetime) -> str:
    return _ensure_utc(value).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return _ensure_utc(parsed)


@dataclass(frozen=True)
class IdempotencyEntry:
    source: str
    skill_id: str
    idempotency_key: str
    expires_at: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "skill_id": self.skill_id,
            "idempotency_key": self.idempotency_key,
            "expires_at": _format_datetime(self.expires_at),
        }


@dataclass(frozen=True)
class IdempotencyDecision:
    allowed: bool
    expires_at: datetime | None


class IdempotencyStore:
    def __init__(
        self,
        path: Path,
        *,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.path = Path(path)
        self._now = now_provider

    def check_and_record(
        self,
        source: str,
        skill_id: str,
        idempotency_key: str,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> IdempotencyDecision:
        with file_lock(self.path):
            now = _ensure_utc(self._now())
            entries = self._prune(self._load_entries(), now)
            scoped_key = self._scoped_key(source, skill_id, idempotency_key)
            entry = entries.get(scoped_key)
            if entry and entry.expires_at > now:
                self._save_entries(entries)
                return IdempotencyDecision(allowed=False, expires_at=entry.expires_at)

            if ttl_seconds <= 0:
                self._save_entries(entries)
                return IdempotencyDecision(allowed=True, expires_at=None)

            expires_at = now + timedelta(seconds=ttl_seconds)
            entries[scoped_key] = IdempotencyEntry(
                source=source,
                skill_id=skill_id,
                idempotency_key=idempotency_key,
                expires_at=expires_at,
            )
            self._save_entries(entries)
            return IdempotencyDecision(allowed=True, expires_at=expires_at)

    def _scoped_key(self, source: str, skill_id: str, idempotency_key: str) -> str:
        return f"{source}:{skill_id}:{idempotency_key}"

    def _load_entries(self) -> dict[str, IdempotencyEntry]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        entries_raw = raw.get("entries", raw)
        if not isinstance(entries_raw, dict):
            return {}
        entries: dict[str, IdempotencyEntry] = {}
        for scoped_key, payload in entries_raw.items():
            if not isinstance(payload, dict):
                continue
            source = str(payload.get("source", "")).strip()
            skill_id = str(payload.get("skill_id", "")).strip()
            key = str(payload.get("idempotency_key", "")).strip()
            expires_raw = payload.get("expires_at")
            if not source or not skill_id or not key or not expires_raw:
                continue
            entries[scoped_key] = IdempotencyEntry(
                source=source,
                skill_id=skill_id,
                idempotency_key=key,
                expires_at=_parse_datetime(str(expires_raw)),
            )
        return entries

    def _save_entries(self, entries: dict[str, IdempotencyEntry]) -> None:
        payload = {
            "entries": {
                key: entry.to_dict() for key, entry in entries.items()
            }
        }
        atomic_write_text(
            self.path,
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def _prune(
        self,
        entries: dict[str, IdempotencyEntry],
        now: datetime,
    ) -> dict[str, IdempotencyEntry]:
        current = _ensure_utc(now)
        return {
            key: entry
            for key, entry in entries.items()
            if entry.expires_at > current
        }


class IdempotencyStorePostgres:
    def __init__(
        self,
        dsn: str,
        *,
        tenant_id: str,
        now_provider: Callable[[], datetime] = _utc_now,
        schema: str = "skillos",
    ) -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._now = now_provider
        self._schema = schema
        self._ensure_table()

    def check_and_record(
        self,
        source: str,
        skill_id: str,
        idempotency_key: str,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> IdempotencyDecision:
        now = _ensure_utc(self._now())
        expires_at = None
        with pg_connect(self._dsn) as conn:
            conn.execute(
                f"DELETE FROM {self._schema}.idempotency_entries "
                "WHERE tenant_id = %s AND expires_at <= %s",
                (self._tenant_id, now),
            )
            row = conn.execute(
                f"""
                SELECT expires_at FROM {self._schema}.idempotency_entries
                WHERE tenant_id = %s AND source = %s AND skill_id = %s
                AND idempotency_key = %s
                """,
                (self._tenant_id, source, skill_id, idempotency_key),
            ).fetchone()
            if row and row.get("expires_at") and row["expires_at"] > now:
                return IdempotencyDecision(allowed=False, expires_at=row["expires_at"])
            if ttl_seconds <= 0:
                return IdempotencyDecision(allowed=True, expires_at=None)
            expires_at = now + timedelta(seconds=ttl_seconds)
            conn.execute(
                f"""
                INSERT INTO {self._schema}.idempotency_entries
                    (tenant_id, source, skill_id, idempotency_key, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, source, skill_id, idempotency_key)
                DO UPDATE SET expires_at = EXCLUDED.expires_at
                """,
                (self._tenant_id, source, skill_id, idempotency_key, expires_at),
            )
        return IdempotencyDecision(allowed=True, expires_at=expires_at)

    def _ensure_table(self) -> None:
        with pg_connect(self._dsn) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._schema}.idempotency_entries (
                    tenant_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (tenant_id, source, skill_id, idempotency_key)
                )
                """
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idempotency_expires_idx
                ON {self._schema}.idempotency_entries (tenant_id, expires_at)
                """
            )


def idempotency_store_from_env(root: Path) -> IdempotencyStore | IdempotencyStorePostgres:
    config = storage_backend_from_env()
    if config.backend != "postgres":
        return IdempotencyStore(default_idempotency_path(root))
    dsn = require_postgres_dsn(config, context="idempotency")
    tenant_id = resolve_tenant_id(Path(root))
    return IdempotencyStorePostgres(
        dsn,
        tenant_id=tenant_id,
        schema=config.postgres_schema,
    )

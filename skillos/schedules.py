from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from uuid import uuid4

from skillos.storage import atomic_write_text
from skillos.tenancy import resolve_tenant_root
from skillos.storage_backend import (
    pg_connect,
    require_postgres_dsn,
    resolve_tenant_id,
    storage_backend_from_env,
)

_TZ_OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")


def default_schedules_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "schedules" / "schedules.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_timezone(value: str | None) -> timezone:
    if not value:
        return timezone.utc
    normalized = value.strip().upper()
    if normalized in {"UTC", "Z"}:
        return timezone.utc
    match = _TZ_OFFSET_RE.match(value.strip())
    if not match:
        return timezone.utc
    sign, hours, minutes = match.groups()
    offset_minutes = int(hours) * 60 + int(minutes)
    if sign == "-":
        offset_minutes = -offset_minutes
    return timezone(timedelta(minutes=offset_minutes))


def parse_run_at(value: str, timezone_hint: str | None = None) -> datetime:
    if not value:
        raise ValueError("run_at is required")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_parse_timezone(timezone_hint))
    return parsed.astimezone(timezone.utc)


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_utc(value).isoformat()


def retry_backoff(
    retry_count: int,
    *,
    base_seconds: int = 5,
    max_seconds: int = 300,
) -> timedelta:
    if retry_count <= 0:
        return timedelta(0)
    delay = base_seconds * (2 ** (retry_count - 1))
    return timedelta(seconds=min(max_seconds, delay))


@dataclass
class ScheduleRecord:
    schedule_id: str
    skill_id: str
    run_at: datetime
    timezone: str | None = None
    payload: str = "ok"
    enabled: bool = True
    last_run: datetime | None = None
    next_run: datetime | None = None
    retries: int = 0
    max_retries: int = 0
    status: str = "pending"
    role: str | None = None
    approval_status: str | None = None
    approval_token: str | None = None
    last_error: str | None = None

    def due_at(self) -> datetime:
        return _ensure_utc(self.next_run or self.run_at)

    def is_due(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        if self.status == "completed":
            return False
        if self.status != "pending" and self.retries >= self.max_retries:
            return False
        return self.due_at() <= _ensure_utc(now)

    def mark_success(self, now: datetime) -> None:
        self.status = "completed"
        self.last_run = _ensure_utc(now)
        self.next_run = None
        self.last_error = None

    def mark_failure(
        self,
        now: datetime,
        reason: str,
        *,
        base_seconds: int = 5,
        max_seconds: int = 300,
    ) -> None:
        self.last_run = _ensure_utc(now)
        self.retries += 1
        self.last_error = reason
        if self.retries <= self.max_retries:
            delay = retry_backoff(
                self.retries,
                base_seconds=base_seconds,
                max_seconds=max_seconds,
            )
            self.next_run = self.last_run + delay
            self.status = "pending"
            return
        self.status = "failed"
        self.next_run = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schedule_id": self.schedule_id,
            "skill_id": self.skill_id,
            "run_at": _format_datetime(self.run_at),
            "timezone": self.timezone,
            "payload": self.payload,
            "enabled": self.enabled,
            "last_run": _format_datetime(self.last_run),
            "next_run": _format_datetime(self.next_run),
            "retries": self.retries,
            "max_retries": self.max_retries,
            "status": self.status,
            "role": self.role,
            "approval_status": self.approval_status,
            "approval_token": self.approval_token,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ScheduleRecord":
        run_at_raw = payload.get("run_at")
        timezone_hint = payload.get("timezone")
        run_at = parse_run_at(str(run_at_raw), str(timezone_hint)) if run_at_raw else _utc_now()
        last_run = payload.get("last_run")
        next_run = payload.get("next_run")
        return cls(
            schedule_id=str(payload.get("schedule_id", "")) or uuid4().hex,
            skill_id=str(payload.get("skill_id", "")),
            run_at=run_at,
            timezone=str(timezone_hint) if timezone_hint else None,
            payload=str(payload.get("payload", "ok")),
            enabled=bool(payload.get("enabled", True)),
            last_run=parse_run_at(str(last_run), None) if last_run else None,
            next_run=parse_run_at(str(next_run), None) if next_run else None,
            retries=int(payload.get("retries", 0) or 0),
            max_retries=int(payload.get("max_retries", 0) or 0),
            status=str(payload.get("status", "pending")),
            role=str(payload.get("role")) if payload.get("role") else None,
            approval_status=str(payload.get("approval_status")) if payload.get("approval_status") else None,
            approval_token=str(payload.get("approval_token")) if payload.get("approval_token") else None,
            last_error=str(payload.get("last_error")) if payload.get("last_error") else None,
        )


class ScheduleStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> list[ScheduleRecord]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("schedules", raw.get("items", []))
        if not isinstance(raw, list):
            return []
        return [
            ScheduleRecord.from_dict(item)
            for item in raw
            if isinstance(item, dict)
        ]

    def save(self, records: list[ScheduleRecord]) -> None:
        payload = {"schedules": [record.to_dict() for record in records]}
        atomic_write_text(
            self.path,
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )


class ScheduleStorePostgres:
    def __init__(self, dsn: str, *, tenant_id: str, schema: str = "skillos") -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._schema = schema
        self._ensure_table()

    def load(self) -> list[ScheduleRecord]:
        query = (
            f"SELECT * FROM {self._schema}.schedules "
            "WHERE tenant_id = %s ORDER BY run_at"
        )
        with pg_connect(self._dsn) as conn:
            rows = conn.execute(query, (self._tenant_id,)).fetchall()
        return [self._from_row(row) for row in rows]

    def save(self, records: list[ScheduleRecord]) -> None:
        with pg_connect(self._dsn) as conn:
            if not records:
                conn.execute(
                    f"DELETE FROM {self._schema}.schedules WHERE tenant_id = %s",
                    (self._tenant_id,),
                )
                return
            schedule_ids = [record.schedule_id for record in records]
            conn.execute(
                f"""
                DELETE FROM {self._schema}.schedules
                WHERE tenant_id = %s AND NOT (schedule_id = ANY(%s))
                """,
                (self._tenant_id, schedule_ids),
            )
            for record in records:
                conn.execute(
                    f"""
                    INSERT INTO {self._schema}.schedules (
                        tenant_id, schedule_id, skill_id, run_at, timezone,
                        payload, enabled, last_run, next_run, retries, max_retries,
                        status, role, approval_status, approval_token, last_error
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (tenant_id, schedule_id) DO UPDATE SET
                        skill_id = EXCLUDED.skill_id,
                        run_at = EXCLUDED.run_at,
                        timezone = EXCLUDED.timezone,
                        payload = EXCLUDED.payload,
                        enabled = EXCLUDED.enabled,
                        last_run = EXCLUDED.last_run,
                        next_run = EXCLUDED.next_run,
                        retries = EXCLUDED.retries,
                        max_retries = EXCLUDED.max_retries,
                        status = EXCLUDED.status,
                        role = EXCLUDED.role,
                        approval_status = EXCLUDED.approval_status,
                        approval_token = EXCLUDED.approval_token,
                        last_error = EXCLUDED.last_error
                    """,
                    (
                        self._tenant_id,
                        record.schedule_id,
                        record.skill_id,
                        _ensure_utc(record.run_at),
                        record.timezone,
                        record.payload,
                        record.enabled,
                        _ensure_utc(record.last_run) if record.last_run else None,
                        _ensure_utc(record.next_run) if record.next_run else None,
                        record.retries,
                        record.max_retries,
                        record.status,
                        record.role,
                        record.approval_status,
                        record.approval_token,
                        record.last_error,
                    ),
                )

    def _ensure_table(self) -> None:
        with pg_connect(self._dsn) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._schema}.schedules (
                    tenant_id TEXT NOT NULL,
                    schedule_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    run_at TIMESTAMPTZ NOT NULL,
                    timezone TEXT,
                    payload TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL,
                    last_run TIMESTAMPTZ,
                    next_run TIMESTAMPTZ,
                    retries INTEGER NOT NULL,
                    max_retries INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    role TEXT,
                    approval_status TEXT,
                    approval_token TEXT,
                    last_error TEXT,
                    PRIMARY KEY (tenant_id, schedule_id)
                )
                """
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS schedules_due_idx
                ON {self._schema}.schedules (tenant_id, run_at, next_run)
                """
            )

    def _from_row(self, row: dict[str, object]) -> ScheduleRecord:
        return ScheduleRecord(
            schedule_id=str(row.get("schedule_id") or ""),
            skill_id=str(row.get("skill_id") or ""),
            run_at=_ensure_utc(row["run_at"]) if row.get("run_at") else _utc_now(),
            timezone=str(row.get("timezone")) if row.get("timezone") else None,
            payload=str(row.get("payload") or "ok"),
            enabled=bool(row.get("enabled", True)),
            last_run=_ensure_utc(row["last_run"]) if row.get("last_run") else None,
            next_run=_ensure_utc(row["next_run"]) if row.get("next_run") else None,
            retries=int(row.get("retries", 0) or 0),
            max_retries=int(row.get("max_retries", 0) or 0),
            status=str(row.get("status") or "pending"),
            role=str(row.get("role")) if row.get("role") else None,
            approval_status=str(row.get("approval_status"))
            if row.get("approval_status")
            else None,
            approval_token=str(row.get("approval_token"))
            if row.get("approval_token")
            else None,
            last_error=str(row.get("last_error"))
            if row.get("last_error")
            else None,
        )


def schedule_store_from_env(root: Path) -> ScheduleStore | ScheduleStorePostgres:
    config = storage_backend_from_env()
    if config.backend != "postgres":
        return ScheduleStore(default_schedules_path(root))
    dsn = require_postgres_dsn(config, context="schedules")
    tenant_id = resolve_tenant_id(Path(root))
    return ScheduleStorePostgres(
        dsn,
        tenant_id=tenant_id,
        schema=config.postgres_schema,
    )


def build_schedule(
    skill_id: str,
    run_at: datetime,
    *,
    timezone: str | None = None,
    payload: str = "ok",
    enabled: bool = True,
    max_retries: int = 0,
    role: str | None = None,
    approval_status: str | None = None,
    approval_token: str | None = None,
) -> ScheduleRecord:
    return ScheduleRecord(
        schedule_id=uuid4().hex,
        skill_id=skill_id,
        run_at=_ensure_utc(run_at),
        timezone=timezone,
        payload=payload,
        enabled=enabled,
        max_retries=max_retries,
        role=role,
        approval_status=approval_status,
        approval_token=approval_token,
    )


def due_schedules(records: list[ScheduleRecord], now: datetime | None = None) -> list[ScheduleRecord]:
    current = _ensure_utc(now) if now else _utc_now()
    return [record for record in records if record.is_due(current)]

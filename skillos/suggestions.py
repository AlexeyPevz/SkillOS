from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from skillos.storage import atomic_write_text
from skillos.tenancy import resolve_tenant_root
from skillos.storage_backend import (
    pg_connect,
    require_postgres_dsn,
    resolve_tenant_id,
    storage_backend_from_env,
)

def default_preferences_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "suggestions" / "preferences.json"


def default_suggestions_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "suggestions" / "suggestions.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    return _ensure_utc(parsed)


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_utc(value).isoformat()


@dataclass
class SuggestionPreferences:
    opt_in: bool = False
    max_per_day: int = 3
    min_interval_minutes: int = 60
    cooldown_minutes_on_dismiss: int = 120
    snoozed_until: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "opt_in": self.opt_in,
            "max_per_day": self.max_per_day,
            "min_interval_minutes": self.min_interval_minutes,
            "cooldown_minutes_on_dismiss": self.cooldown_minutes_on_dismiss,
            "snoozed_until": _format_datetime(self.snoozed_until),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SuggestionPreferences":
        opt_in = bool(payload.get("opt_in", False))
        max_per_day = int(payload.get("max_per_day", 3))
        min_interval_minutes = int(payload.get("min_interval_minutes", 60))
        cooldown_minutes = int(payload.get("cooldown_minutes_on_dismiss", 120))
        snoozed_until_raw = payload.get("snoozed_until")
        snoozed_until = (
            _parse_datetime(str(snoozed_until_raw)) if snoozed_until_raw else None
        )
        return cls(
            opt_in=opt_in,
            max_per_day=max_per_day,
            min_interval_minutes=min_interval_minutes,
            cooldown_minutes_on_dismiss=cooldown_minutes,
            snoozed_until=snoozed_until,
        )


@dataclass
class SuggestionRecord:
    suggestion_id: str
    source: str
    summary: str
    message: str
    created_at: datetime
    status: str = "created"
    dismissed_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "suggestion_id": self.suggestion_id,
            "source": self.source,
            "summary": self.summary,
            "message": self.message,
            "created_at": _format_datetime(self.created_at),
            "status": self.status,
            "dismissed_at": _format_datetime(self.dismissed_at),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SuggestionRecord":
        raw_created_at = payload.get("created_at")
        created_at = (
            _parse_datetime(str(raw_created_at)) if raw_created_at else None
        )
        return cls(
            suggestion_id=str(payload.get("suggestion_id", "")),
            source=str(payload.get("source", "")),
            summary=str(payload.get("summary", "")),
            message=str(payload.get("message", "")),
            created_at=created_at or _utc_now(),
            status=str(payload.get("status", "created")),
            dismissed_at=_parse_datetime(str(payload.get("dismissed_at")))
            if payload.get("dismissed_at")
            else None,
        )


class SuggestionPreferencesStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> SuggestionPreferences:
        if not self.path.exists():
            return SuggestionPreferences()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return SuggestionPreferences()
        return SuggestionPreferences.from_dict(raw)

    def save(self, preferences: SuggestionPreferences) -> None:
        atomic_write_text(
            self.path,
            json.dumps(preferences.to_dict(), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )


class SuggestionStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> list[SuggestionRecord]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("suggestions", [])
        if not isinstance(raw, list):
            return []
        records: list[SuggestionRecord] = []
        for item in raw:
            if isinstance(item, dict):
                records.append(SuggestionRecord.from_dict(item))
        return records

    def save(self, records: list[SuggestionRecord]) -> None:
        payload = {"suggestions": [record.to_dict() for record in records]}
        atomic_write_text(
            self.path,
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )


class SuggestionPreferencesStorePostgres:
    def __init__(self, dsn: str, *, tenant_id: str, schema: str = "skillos") -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._schema = schema
        self._ensure_table()

    def load(self) -> SuggestionPreferences:
        query = (
            f"SELECT opt_in, max_per_day, min_interval_minutes, "
            f"cooldown_minutes_on_dismiss, snoozed_until "
            f"FROM {self._schema}.suggestion_preferences WHERE tenant_id = %s"
        )
        with pg_connect(self._dsn) as conn:
            row = conn.execute(query, (self._tenant_id,)).fetchone()
        if not row:
            return SuggestionPreferences()
        return SuggestionPreferences(
            opt_in=bool(row.get("opt_in", False)),
            max_per_day=int(row.get("max_per_day", 3)),
            min_interval_minutes=int(row.get("min_interval_minutes", 60)),
            cooldown_minutes_on_dismiss=int(row.get("cooldown_minutes_on_dismiss", 120)),
            snoozed_until=_ensure_utc(row["snoozed_until"])
            if row.get("snoozed_until")
            else None,
        )

    def save(self, preferences: SuggestionPreferences) -> None:
        query = (
            f"""
            INSERT INTO {self._schema}.suggestion_preferences (
                tenant_id, opt_in, max_per_day, min_interval_minutes,
                cooldown_minutes_on_dismiss, snoozed_until
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO UPDATE SET
                opt_in = EXCLUDED.opt_in,
                max_per_day = EXCLUDED.max_per_day,
                min_interval_minutes = EXCLUDED.min_interval_minutes,
                cooldown_minutes_on_dismiss = EXCLUDED.cooldown_minutes_on_dismiss,
                snoozed_until = EXCLUDED.snoozed_until,
                updated_at = now()
            """
        )
        with pg_connect(self._dsn) as conn:
            conn.execute(
                query,
                (
                    self._tenant_id,
                    preferences.opt_in,
                    preferences.max_per_day,
                    preferences.min_interval_minutes,
                    preferences.cooldown_minutes_on_dismiss,
                    _ensure_utc(preferences.snoozed_until)
                    if preferences.snoozed_until
                    else None,
                ),
            )

    def _ensure_table(self) -> None:
        with pg_connect(self._dsn) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._schema}.suggestion_preferences (
                    tenant_id TEXT PRIMARY KEY,
                    opt_in BOOLEAN NOT NULL,
                    max_per_day INTEGER NOT NULL,
                    min_interval_minutes INTEGER NOT NULL,
                    cooldown_minutes_on_dismiss INTEGER NOT NULL,
                    snoozed_until TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )


class SuggestionStorePostgres:
    def __init__(self, dsn: str, *, tenant_id: str, schema: str = "skillos") -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._schema = schema
        self._ensure_table()

    def load(self) -> list[SuggestionRecord]:
        query = (
            f"SELECT * FROM {self._schema}.suggestions "
            "WHERE tenant_id = %s ORDER BY created_at"
        )
        with pg_connect(self._dsn) as conn:
            rows = conn.execute(query, (self._tenant_id,)).fetchall()
        records: list[SuggestionRecord] = []
        for row in rows:
            records.append(
                SuggestionRecord(
                    suggestion_id=str(row.get("suggestion_id") or ""),
                    source=str(row.get("source") or ""),
                    summary=str(row.get("summary") or ""),
                    message=str(row.get("message") or ""),
                    created_at=_ensure_utc(row["created_at"])
                    if row.get("created_at")
                    else _utc_now(),
                    status=str(row.get("status") or "created"),
                    dismissed_at=_ensure_utc(row["dismissed_at"])
                    if row.get("dismissed_at")
                    else None,
                )
            )
        return records

    def save(self, records: list[SuggestionRecord]) -> None:
        with pg_connect(self._dsn) as conn:
            if not records:
                conn.execute(
                    f"DELETE FROM {self._schema}.suggestions WHERE tenant_id = %s",
                    (self._tenant_id,),
                )
                return
            suggestion_ids = [record.suggestion_id for record in records]
            conn.execute(
                f"""
                DELETE FROM {self._schema}.suggestions
                WHERE tenant_id = %s AND NOT (suggestion_id = ANY(%s))
                """,
                (self._tenant_id, suggestion_ids),
            )
            for record in records:
                conn.execute(
                    f"""
                    INSERT INTO {self._schema}.suggestions (
                        tenant_id, suggestion_id, source, summary, message,
                        created_at, status, dismissed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, suggestion_id) DO UPDATE SET
                        source = EXCLUDED.source,
                        summary = EXCLUDED.summary,
                        message = EXCLUDED.message,
                        created_at = EXCLUDED.created_at,
                        status = EXCLUDED.status,
                        dismissed_at = EXCLUDED.dismissed_at
                    """,
                    (
                        self._tenant_id,
                        record.suggestion_id,
                        record.source,
                        record.summary,
                        record.message,
                        _ensure_utc(record.created_at),
                        record.status,
                        _ensure_utc(record.dismissed_at)
                        if record.dismissed_at
                        else None,
                    ),
                )

    def _ensure_table(self) -> None:
        with pg_connect(self._dsn) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._schema}.suggestions (
                    tenant_id TEXT NOT NULL,
                    suggestion_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    status TEXT NOT NULL,
                    dismissed_at TIMESTAMPTZ,
                    PRIMARY KEY (tenant_id, suggestion_id)
                )
                """
            )


def preferences_store_from_env(
    root: Path,
) -> SuggestionPreferencesStore | SuggestionPreferencesStorePostgres:
    config = storage_backend_from_env()
    if config.backend != "postgres":
        return SuggestionPreferencesStore(default_preferences_path(root))
    dsn = require_postgres_dsn(config, context="suggestions")
    tenant_id = resolve_tenant_id(Path(root))
    return SuggestionPreferencesStorePostgres(
        dsn,
        tenant_id=tenant_id,
        schema=config.postgres_schema,
    )


def suggestion_store_from_env(
    root: Path,
) -> SuggestionStore | SuggestionStorePostgres:
    config = storage_backend_from_env()
    if config.backend != "postgres":
        return SuggestionStore(default_suggestions_path(root))
    dsn = require_postgres_dsn(config, context="suggestions")
    tenant_id = resolve_tenant_id(Path(root))
    return SuggestionStorePostgres(
        dsn,
        tenant_id=tenant_id,
        schema=config.postgres_schema,
    )

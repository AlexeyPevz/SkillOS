from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import time
from typing import Callable, Iterator
from uuid import uuid4
from contextlib import contextmanager

from skillos.orchestrator import Orchestrator
from skillos.execution_planner import build_execution_plan
from skillos.routing import to_internal_id, to_public_id
from skillos.telemetry import (
    EventLogger,
    default_log_path,
    log_job_failed,
    log_job_started,
    log_job_succeeded,
    new_request_id,
)
from skillos.tenancy import resolve_tenant_root
from skillos.storage_backend import (
    pg_connect,
    require_postgres_dsn,
    resolve_tenant_id,
    storage_backend_from_env,
)


def default_jobs_db_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "runtime" / "jobs.db"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_utc(value).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return _ensure_utc(parsed)


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
class JobRecord:
    job_id: str
    skill_id: str
    payload: str
    status: str
    retries: int
    max_retries: int
    created_at: datetime
    updated_at: datetime
    next_run_at: datetime | None = None
    last_error: str | None = None

    def is_due(self, now: datetime) -> bool:
        if self.status != "queued":
            return False
        due_at = self.next_run_at or self.created_at
        return _ensure_utc(due_at) <= _ensure_utc(now)

    def mark_running(self, now: datetime) -> None:
        self.status = "running"
        self.updated_at = _ensure_utc(now)
        self.next_run_at = None

    def mark_succeeded(self, now: datetime) -> None:
        self.status = "succeeded"
        self.updated_at = _ensure_utc(now)
        self.next_run_at = None
        self.last_error = None

    def mark_failed(
        self,
        now: datetime,
        error: str,
        *,
        base_seconds: int = 5,
        max_seconds: int = 300,
    ) -> bool:
        self.retries += 1
        self.last_error = error
        self.updated_at = _ensure_utc(now)
        if self.retries <= self.max_retries:
            delay = retry_backoff(
                self.retries,
                base_seconds=base_seconds,
                max_seconds=max_seconds,
            )
            self.status = "queued"
            self.next_run_at = self.updated_at + delay
            return True
        self.status = "failed"
        self.next_run_at = None
        return False

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "skill_id": self.skill_id,
            "payload": self.payload,
            "status": self.status,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "created_at": _format_datetime(self.created_at),
            "updated_at": _format_datetime(self.updated_at),
            "next_run_at": _format_datetime(self.next_run_at),
            "last_error": self.last_error,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "JobRecord":
        return cls(
            job_id=str(row["job_id"]),
            skill_id=str(row["skill_id"]),
            payload=str(row["payload"]),
            status=str(row["status"]),
            retries=int(row["retries"]),
            max_retries=int(row["max_retries"]),
            created_at=_parse_datetime(row["created_at"]) or _utc_now(),
            updated_at=_parse_datetime(row["updated_at"]) or _utc_now(),
            next_run_at=_parse_datetime(row["next_run_at"]),
            last_error=str(row["last_error"]) if row["last_error"] else None,
        )


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._ensure_db()

    def enqueue(
        self,
        skill_id: str,
        *,
        payload: str = "ok",
        max_retries: int = 0,
        job_id: str | None = None,
        now: datetime | None = None,
    ) -> JobRecord:
        created_at = _ensure_utc(now or _utc_now())
        record = JobRecord(
            job_id=job_id or uuid4().hex,
            skill_id=skill_id,
            payload=payload,
            status="queued",
            retries=0,
            max_retries=max_retries,
            created_at=created_at,
            updated_at=created_at,
            next_run_at=created_at,
            last_error=None,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, skill_id, payload, status, retries, max_retries,
                    created_at, updated_at, next_run_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job_id,
                    record.skill_id,
                    record.payload,
                    record.status,
                    record.retries,
                    record.max_retries,
                    _format_datetime(record.created_at),
                    _format_datetime(record.updated_at),
                    _format_datetime(record.next_run_at),
                    record.last_error,
                ),
            )
        return record

    def fetch_due(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[JobRecord]:
        due_at = _format_datetime(_ensure_utc(now or _utc_now()))
        query = (
            "SELECT * FROM jobs WHERE status = ? "
            "AND (next_run_at IS NULL OR next_run_at <= ?) "
            "ORDER BY created_at"
        )
        params: list[object] = ["queued", due_at]
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [JobRecord.from_row(row) for row in rows]

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return JobRecord.from_row(row) if row else None

    def save(self, record: JobRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET skill_id = ?,
                    payload = ?,
                    status = ?,
                    retries = ?,
                    max_retries = ?,
                    created_at = ?,
                    updated_at = ?,
                    next_run_at = ?,
                    last_error = ?
                WHERE job_id = ?
                """,
                (
                    record.skill_id,
                    record.payload,
                    record.status,
                    record.retries,
                    record.max_retries,
                    _format_datetime(record.created_at),
                    _format_datetime(record.updated_at),
                    _format_datetime(record.next_run_at),
                    record.last_error,
                    record.job_id,
                ),
            )

    def list_all(self) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
        return [JobRecord.from_row(row) for row in rows]

    def requeue_dead_letters(self, max_retries_bump: int = 1) -> int:
        """
        Resets 'failed' jobs to 'queued' and increments max_retries to allow another attempt.
        Returns count of requeued jobs.
        """
        with self._connect() as conn:
            # Atomic update for SQLite
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'queued',
                    max_retries = max_retries + ?,
                    next_run_at = ?,
                    updated_at = ?
                WHERE status = 'failed'
                """,
                (max_retries_bump, _format_datetime(_utc_now()), _format_datetime(_utc_now()))
            )
            return cursor.rowcount

    def _ensure_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retries INTEGER NOT NULL,
                    max_retries INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_run_at TEXT,
                    last_error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_status_run
                ON jobs (status, next_run_at)
                """
            )
            conn.commit()
        finally:
            conn.close()


    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except:
            conn.rollback()
            raise
        finally:
            conn.close()


class JobStorePostgres:
    def __init__(self, dsn: str, *, tenant_id: str, schema: str = "skillos") -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._schema = schema
        self._ensure_db()

    def enqueue(
        self,
        skill_id: str,
        *,
        payload: str = "ok",
        max_retries: int = 0,
        job_id: str | None = None,
        now: datetime | None = None,
    ) -> JobRecord:
        created_at = _ensure_utc(now or _utc_now())
        record = JobRecord(
            job_id=job_id or uuid4().hex,
            skill_id=skill_id,
            payload=payload,
            status="queued",
            retries=0,
            max_retries=max_retries,
            created_at=created_at,
            updated_at=created_at,
            next_run_at=created_at,
            last_error=None,
        )
        with pg_connect(self._dsn) as conn:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.jobs (
                    tenant_id, job_id, skill_id, payload, status, retries, max_retries,
                    created_at, updated_at, next_run_at, last_error
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self._tenant_id,
                    record.job_id,
                    record.skill_id,
                    record.payload,
                    record.status,
                    record.retries,
                    record.max_retries,
                    _format_datetime(record.created_at),
                    _format_datetime(record.updated_at),
                    _format_datetime(record.next_run_at),
                    record.last_error,
                ),
            )
        return record

    def fetch_due(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[JobRecord]:
        due_at = _format_datetime(_ensure_utc(now or _utc_now()))
        query = (
            f"SELECT * FROM {self._schema}.jobs "
            "WHERE tenant_id = %s AND status = %s "
            "AND (next_run_at IS NULL OR next_run_at <= %s) "
            "ORDER BY created_at"
        )
        params: list[object] = [self._tenant_id, "queued", due_at]
        if limit is not None:
            query += " LIMIT %s"
            params.append(int(limit))
        with pg_connect(self._dsn) as conn:
            rows = conn.execute(query, params).fetchall()
        return [JobRecord.from_row(_pg_row_to_sqlite(row)) for row in rows]

    def get(self, job_id: str) -> JobRecord | None:
        with pg_connect(self._dsn) as conn:
            row = conn.execute(
                f"SELECT * FROM {self._schema}.jobs WHERE tenant_id = %s AND job_id = %s",
                (self._tenant_id, job_id),
            ).fetchone()
        return JobRecord.from_row(_pg_row_to_sqlite(row)) if row else None

    def save(self, record: JobRecord) -> None:
        with pg_connect(self._dsn) as conn:
            conn.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET skill_id = %s,
                    payload = %s,
                    status = %s,
                    retries = %s,
                    max_retries = %s,
                    created_at = %s,
                    updated_at = %s,
                    next_run_at = %s,
                    last_error = %s
                WHERE tenant_id = %s AND job_id = %s
                """,
                (
                    record.skill_id,
                    record.payload,
                    record.status,
                    record.retries,
                    record.max_retries,
                    _format_datetime(record.created_at),
                    _format_datetime(record.updated_at),
                    _format_datetime(record.next_run_at),
                    record.last_error,
                    self._tenant_id,
                    record.job_id,
                ),
            )

    def list_all(self) -> list[JobRecord]:
        with pg_connect(self._dsn) as conn:
            rows = conn.execute(
                f"SELECT * FROM {self._schema}.jobs "
                "WHERE tenant_id = %s ORDER BY created_at",
                (self._tenant_id,),
            ).fetchall()
        return [JobRecord.from_row(_pg_row_to_sqlite(row)) for row in rows]

    def requeue_dead_letters(self, max_retries_bump: int = 1) -> int:
        with pg_connect(self._dsn) as conn:
            cursor = conn.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status = %s,
                    max_retries = max_retries + %s,
                    next_run_at = %s,
                    updated_at = %s
                WHERE tenant_id = %s AND status = %s
                """,
                (
                    "queued",
                    max_retries_bump,
                    _format_datetime(_utc_now()),
                    _format_datetime(_utc_now()),
                    self._tenant_id,
                    "failed",
                )
            )
            return cursor.rowcount

    def _ensure_db(self) -> None:
        with pg_connect(self._dsn) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._schema}.jobs (
                    tenant_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retries INTEGER NOT NULL,
                    max_retries INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_run_at TEXT,
                    last_error TEXT,
                    PRIMARY KEY (tenant_id, job_id)
                )
                """
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS jobs_status_run_idx
                ON {self._schema}.jobs (tenant_id, status, next_run_at)
                """
            )


def _pg_row_to_sqlite(row: dict[str, object]) -> sqlite3.Row:
    class _Row(dict):
        def __getattr__(self, name: str):
            return self[name]

    return _Row(row)  # type: ignore[return-value]


def job_store_from_env(root: Path) -> JobStore | JobStorePostgres:
    config = storage_backend_from_env()
    if config.backend != "postgres":
        return JobStore(default_jobs_db_path(root))
    dsn = require_postgres_dsn(config, context="jobs")
    tenant_id = resolve_tenant_id(Path(root))
    return JobStorePostgres(
        dsn,
        tenant_id=tenant_id,
        schema=config.postgres_schema,
    )


class JobWorker:
    def __init__(
        self,
        root_path: Path,
        store: JobStore,
        *,
        log_path: Path | None = None,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.root_path = Path(root_path)
        self.store = store
        self.log_path = log_path or default_log_path(self.root_path)
        self._now = now_provider

        self.orchestrator = Orchestrator(self.root_path, self.log_path)

    def run_once(self, *, limit: int | None = None) -> list[JobRecord]:
        now = self._now()
        jobs = self.store.fetch_due(now=now, limit=limit)
        results: list[JobRecord] = []
        for job in jobs:
            results.append(self._execute_job(job))
        return results

    def _execute_job(self, job: JobRecord) -> JobRecord:
        now = self._now()
        logger = EventLogger(self.log_path, request_id=new_request_id())
        job.mark_running(now)
        self.store.save(job)
        log_job_started(
            logger,
            job_id=job.job_id,
            skill_id=job.skill_id,
            status=job.status,
            retries=job.retries,
            max_retries=job.max_retries,
        )

        start = time.perf_counter()
        internal_skill_id = to_internal_id(job.skill_id)
        metadata = self.orchestrator.registry.get(internal_skill_id)
        if metadata is None:
            return self._fail_job(job, logger, now, "unknown_skill", start)

        plan = build_execution_plan(
            to_public_id(internal_skill_id),
            internal_skill_id,
            job.payload,
        )

        try:
            result = self.orchestrator.execute_plan(
                plan,
                execute=True,
                dry_run=False,
                approval=None,
                approval_token=None,
                role=None,
                attributes=None,
                plan_path=None,
                debug_trace=None,
                logger=logger,
                request_start=start,
                metadata=metadata,
                warnings=None,
                skill_selected=None,
            )
        except Exception as exc:  # pragma: no cover - execution exceptions
            return self._fail_job(
                job,
                logger,
                now,
                exc.__class__.__name__,
                start,
                log_execution_result=False,
            )

        if result.get("status") != "success":
            reason = result.get("reason") or result.get("policy_id") or "blocked"
            return self._fail_job(
                job,
                logger,
                now,
                reason,
                start,
                log_execution_result=False,
            )

        duration_ms = (time.perf_counter() - start) * 1000
        job.mark_succeeded(now)
        self.store.save(job)
        log_job_succeeded(
            logger,
            job_id=job.job_id,
            skill_id=job.skill_id,
            status=job.status,
            duration_ms=duration_ms,
        )
        return job

    def _fail_job(
        self,
        job: JobRecord,
        logger: EventLogger,
        now: datetime,
        error_class: str,
        start: float,
        *,
        log_execution_result: bool = True,
    ) -> JobRecord:
        duration_ms = (time.perf_counter() - start) * 1000
        if log_execution_result:
            logger.log(
                "execution_result",
                status="error",
                duration_ms=duration_ms,
                error_class=error_class,
            )
        will_retry = job.mark_failed(now, error_class)
        self.store.save(job)
        log_job_failed(
            logger,
            job_id=job.job_id,
            skill_id=job.skill_id,
            status=job.status,
            error_class=error_class,
            retries=job.retries,
            max_retries=job.max_retries,
            next_run_at=_format_datetime(job.next_run_at),
            retrying=will_retry,
        )
        return job

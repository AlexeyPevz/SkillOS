from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from typing import Callable, Iterator
import json

from skillos.storage import atomic_write_text, file_lock
from skillos.tenancy import resolve_tenant_root
from skillos.storage_backend import (
    pg_connect,
    require_postgres_dsn,
    resolve_tenant_id,
    storage_backend_from_env,
)

def default_budget_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "budget" / "usage.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class BudgetConfig:
    per_request_limit: float = 5.0
    daily_limit: float = 50.0
    monthly_limit: float = 200.0
    low_remaining_threshold: float = 10.0
    standard_model: str = "standard"
    cheap_model: str = "budget"
    standard_cost: float = 1.0
    cheap_cost: float = 0.5


def budget_config_from_env() -> BudgetConfig:
    return BudgetConfig(
        per_request_limit=_env_float("SKILLOS_BUDGET_PER_REQUEST", 5.0),
        daily_limit=_env_float("SKILLOS_BUDGET_DAILY", 50.0),
        monthly_limit=_env_float("SKILLOS_BUDGET_MONTHLY", 200.0),
        low_remaining_threshold=_env_float("SKILLOS_BUDGET_LOW_REMAINING", 10.0),
        standard_cost=_env_float("SKILLOS_MODEL_STANDARD_COST", 1.0),
        cheap_cost=_env_float("SKILLOS_MODEL_CHEAP_COST", 0.5),
    )


@dataclass(frozen=True)
class BudgetCheckResult:
    allowed: bool
    reason: str | None
    model: str
    estimated_cost: float
    remaining_daily: float
    remaining_monthly: float
    day_key: str
    month_key: str


@dataclass
class BudgetUsage:
    daily: dict[str, float]
    monthly: dict[str, float]


class BudgetUsageStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> BudgetUsage:
        if not self.path.exists():
            return BudgetUsage(daily={}, monthly={})
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        daily = {key: float(value) for key, value in raw.get("daily", {}).items()}
        monthly = {
            key: float(value) for key, value in raw.get("monthly", {}).items()
        }
        return BudgetUsage(daily=daily, monthly=monthly)

    def save(self, usage: BudgetUsage) -> None:
        payload = {"daily": usage.daily, "monthly": usage.monthly}
        atomic_write_text(
            self.path,
            json.dumps(payload, ensure_ascii=True),
            encoding="utf-8",
        )


class BudgetUsageStorePostgres:
    def __init__(self, dsn: str, *, tenant_id: str, schema: str = "skillos") -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._schema = schema
        self._ensure_table()

    def load(self) -> BudgetUsage:
        query = (
            f"SELECT daily, monthly FROM {self._schema}.budget_usage "
            "WHERE tenant_id = %s"
        )
        with pg_connect(self._dsn) as conn:
            row = conn.execute(query, (self._tenant_id,)).fetchone()
        if not row:
            return BudgetUsage(daily={}, monthly={})
        daily = row.get("daily") or {}
        monthly = row.get("monthly") or {}
        return BudgetUsage(
            daily={key: float(value) for key, value in daily.items()},
            monthly={key: float(value) for key, value in monthly.items()},
        )

    def save(self, usage: BudgetUsage) -> None:
        query = (
            f"INSERT INTO {self._schema}.budget_usage "
            "(tenant_id, daily, monthly) "
            "VALUES (%s, %s::jsonb, %s::jsonb) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "daily = EXCLUDED.daily, monthly = EXCLUDED.monthly, updated_at = now()"
        )
        with pg_connect(self._dsn) as conn:
            conn.execute(
                query,
                (
                    self._tenant_id,
                    json.dumps(usage.daily, ensure_ascii=True),
                    json.dumps(usage.monthly, ensure_ascii=True),
                ),
            )

    def _ensure_table(self) -> None:
        with pg_connect(self._dsn) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._schema}.budget_usage (
                    tenant_id TEXT PRIMARY KEY,
                    daily JSONB NOT NULL,
                    monthly JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

    @contextmanager
    def transaction(self) -> Iterator["_BudgetUsageStorePostgresTx"]:
        lock_key = _advisory_lock_key(f"{self._schema}:{self._tenant_id}")
        with pg_connect(self._dsn) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
            yield _BudgetUsageStorePostgresTx(
                conn,
                tenant_id=self._tenant_id,
                schema=self._schema,
            )


class _BudgetUsageStorePostgresTx:
    def __init__(self, conn, *, tenant_id: str, schema: str) -> None:
        self._conn = conn
        self._tenant_id = tenant_id
        self._schema = schema

    def load(self) -> BudgetUsage:
        query = (
            f"SELECT daily, monthly FROM {self._schema}.budget_usage "
            "WHERE tenant_id = %s"
        )
        row = self._conn.execute(query, (self._tenant_id,)).fetchone()
        if not row:
            return BudgetUsage(daily={}, monthly={})
        daily = row.get("daily") or {}
        monthly = row.get("monthly") or {}
        return BudgetUsage(
            daily={key: float(value) for key, value in daily.items()},
            monthly={key: float(value) for key, value in monthly.items()},
        )

    def save(self, usage: BudgetUsage) -> None:
        query = (
            f"INSERT INTO {self._schema}.budget_usage "
            "(tenant_id, daily, monthly) "
            "VALUES (%s, %s::jsonb, %s::jsonb) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "daily = EXCLUDED.daily, monthly = EXCLUDED.monthly, updated_at = now()"
        )
        self._conn.execute(
            query,
            (
                self._tenant_id,
                json.dumps(usage.daily, ensure_ascii=True),
                json.dumps(usage.monthly, ensure_ascii=True),
            ),
        )


def _advisory_lock_key(tenant_id: str) -> int:
    digest = hashlib.blake2b(tenant_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def budget_usage_store_from_env(root: Path) -> BudgetUsageStore | BudgetUsageStorePostgres:
    config = storage_backend_from_env()
    if config.backend != "postgres":
        return BudgetUsageStore(default_budget_path(root))
    dsn = require_postgres_dsn(config, context="budget")
    tenant_id = resolve_tenant_id(Path(root))
    return BudgetUsageStorePostgres(
        dsn,
        tenant_id=tenant_id,
        schema=config.postgres_schema,
    )


class BudgetManager:
    def __init__(
        self,
        store: BudgetUsageStore,
        config: BudgetConfig | None = None,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._config = config or BudgetConfig()
        self._now = now_provider

    def authorize(self) -> BudgetCheckResult:
        with self._store_lock() as store:
            result = self._evaluate_with_store(store)
            if result.allowed:
                self._record_with_store(store, result)
            return result

    def evaluate(self) -> BudgetCheckResult:
        return self._evaluate_with_store(self._store)

    def record(self, result: BudgetCheckResult, *, already_locked: bool = False) -> None:
        if already_locked:
            self._record_with_store(self._store, result)
            return
        with self._store_lock() as store:
            self._record_with_store(store, result)

    def _evaluate_with_store(self, store) -> BudgetCheckResult:
        usage = store.load()
        now = self._now()
        day_key = now.date().isoformat()
        month_key = f"{now.year:04d}-{now.month:02d}"

        daily_used = usage.daily.get(day_key, 0.0)
        monthly_used = usage.monthly.get(month_key, 0.0)

        remaining_daily = self._config.daily_limit - daily_used
        remaining_monthly = self._config.monthly_limit - monthly_used

        model = self._select_model(remaining_daily, remaining_monthly)
        estimated_cost = self._cost_for(model)

        allowed = True
        reason = None
        if estimated_cost > self._config.per_request_limit:
            allowed = False
            reason = "per_request_limit_exceeded"
        elif estimated_cost > remaining_daily:
            allowed = False
            reason = "daily_limit_exceeded"
        elif estimated_cost > remaining_monthly:
            allowed = False
            reason = "monthly_limit_exceeded"

        return BudgetCheckResult(
            allowed=allowed,
            reason=reason,
            model=model,
            estimated_cost=estimated_cost,
            remaining_daily=remaining_daily,
            remaining_monthly=remaining_monthly,
            day_key=day_key,
            month_key=month_key,
        )

    def _record_with_store(self, store, result: BudgetCheckResult) -> None:
        usage = store.load()
        daily_used = usage.daily.get(result.day_key, 0.0)
        monthly_used = usage.monthly.get(result.month_key, 0.0)

        usage.daily[result.day_key] = daily_used + result.estimated_cost
        usage.monthly[result.month_key] = monthly_used + result.estimated_cost
        store.save(usage)

    @contextmanager
    def _store_lock(self) -> Iterator[object]:
        if hasattr(self._store, "transaction"):
            with self._store.transaction() as store:
                yield store
            return
        with file_lock(self._store.path):
            yield self._store

    def _select_model(self, remaining_daily: float, remaining_monthly: float) -> str:
        remaining_budget = min(remaining_daily, remaining_monthly)
        if remaining_budget <= self._config.low_remaining_threshold:
            return self._config.cheap_model
        return self._config.standard_model

    def _cost_for(self, model: str) -> float:
        if model == self._config.cheap_model:
            return self._config.cheap_cost
        return self._config.standard_cost

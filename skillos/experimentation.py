from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
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

def default_experiment_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "experiments" / "experiments.json"


@dataclass
class VariantMetrics:
    successes: int = 0
    failures: int = 0

    @property
    def total(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.successes / self.total

    def record(self, success: bool) -> None:
        if success:
            self.successes += 1
        else:
            self.failures += 1

    def to_dict(self) -> dict[str, int]:
        return {"successes": self.successes, "failures": self.failures}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "VariantMetrics":
        return cls(
            successes=int(payload.get("successes", 0)),
            failures=int(payload.get("failures", 0)),
        )


@dataclass
class ExperimentState:
    baseline_variant: str
    active_variant: str
    variants: dict[str, VariantMetrics] = field(default_factory=dict)
    previous_variant: str | None = None

    def ensure_variant(self, variant_id: str) -> VariantMetrics:
        if variant_id not in self.variants:
            self.variants[variant_id] = VariantMetrics()
        return self.variants[variant_id]

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline_variant": self.baseline_variant,
            "active_variant": self.active_variant,
            "previous_variant": self.previous_variant,
            "variants": {
                variant_id: metrics.to_dict()
                for variant_id, metrics in self.variants.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ExperimentState":
        baseline = str(payload.get("baseline_variant") or "")
        active = str(payload.get("active_variant") or baseline)
        previous_variant = payload.get("previous_variant")
        raw_variants = payload.get("variants", {})
        variants: dict[str, VariantMetrics] = {}
        if isinstance(raw_variants, dict):
            for variant_id, metrics_payload in raw_variants.items():
                if isinstance(metrics_payload, dict):
                    variants[variant_id] = VariantMetrics.from_dict(metrics_payload)
        if baseline and baseline not in variants:
            variants[baseline] = VariantMetrics()
        if active and active not in variants:
            variants[active] = VariantMetrics()
        return cls(
            baseline_variant=baseline or active,
            active_variant=active or baseline,
            previous_variant=previous_variant if isinstance(previous_variant, str) else None,
            variants=variants,
        )


class ExperimentStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, ExperimentState]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        experiments = raw.get("experiments", raw)
        if not isinstance(experiments, dict):
            return {}
        parsed: dict[str, ExperimentState] = {}
        for experiment_id, payload in experiments.items():
            if isinstance(payload, dict):
                parsed[experiment_id] = ExperimentState.from_dict(payload)
        return parsed

    def save(self, experiments: dict[str, ExperimentState]) -> None:
        payload = {
            "experiments": {
                experiment_id: state.to_dict()
                for experiment_id, state in experiments.items()
            }
        }
        atomic_write_text(
            self.path,
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def get(self, experiment_id: str) -> ExperimentState | None:
        return self.load().get(experiment_id)

    def upsert(self, experiment_id: str, state: ExperimentState) -> None:
        experiments = self.load()
        experiments[experiment_id] = state
        self.save(experiments)


class ExperimentStorePostgres:
    def __init__(self, dsn: str, *, tenant_id: str, schema: str = "skillos") -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._schema = schema
        self._ensure_table()

    def load(self) -> dict[str, ExperimentState]:
        query = (
            f"SELECT experiment_id, baseline_variant, active_variant, "
            f"previous_variant, variants FROM {self._schema}.experiments "
            "WHERE tenant_id = %s"
        )
        with pg_connect(self._dsn) as conn:
            rows = conn.execute(query, (self._tenant_id,)).fetchall()
        parsed: dict[str, ExperimentState] = {}
        for row in rows:
            payload = {
                "baseline_variant": row.get("baseline_variant"),
                "active_variant": row.get("active_variant"),
                "previous_variant": row.get("previous_variant"),
                "variants": row.get("variants") or {},
            }
            parsed[str(row.get("experiment_id"))] = ExperimentState.from_dict(payload)
        return parsed

    def save(self, experiments: dict[str, ExperimentState]) -> None:
        with pg_connect(self._dsn) as conn:
            if not experiments:
                conn.execute(
                    f"DELETE FROM {self._schema}.experiments WHERE tenant_id = %s",
                    (self._tenant_id,),
                )
                return
            experiment_ids = list(experiments.keys())
            conn.execute(
                f"""
                DELETE FROM {self._schema}.experiments
                WHERE tenant_id = %s AND NOT (experiment_id = ANY(%s))
                """,
                (self._tenant_id, experiment_ids),
            )
            for experiment_id, state in experiments.items():
                conn.execute(
                    f"""
                    INSERT INTO {self._schema}.experiments (
                        tenant_id, experiment_id, baseline_variant, active_variant,
                        previous_variant, variants
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (tenant_id, experiment_id) DO UPDATE SET
                        baseline_variant = EXCLUDED.baseline_variant,
                        active_variant = EXCLUDED.active_variant,
                        previous_variant = EXCLUDED.previous_variant,
                        variants = EXCLUDED.variants,
                        updated_at = now()
                    """,
                    (
                        self._tenant_id,
                        experiment_id,
                        state.baseline_variant,
                        state.active_variant,
                        state.previous_variant,
                        json.dumps(state.to_dict().get("variants", {}), ensure_ascii=True),
                    ),
                )

    def get(self, experiment_id: str) -> ExperimentState | None:
        query = (
            f"SELECT baseline_variant, active_variant, previous_variant, variants "
            f"FROM {self._schema}.experiments WHERE tenant_id = %s AND experiment_id = %s"
        )
        with pg_connect(self._dsn) as conn:
            row = conn.execute(query, (self._tenant_id, experiment_id)).fetchone()
        if not row:
            return None
        payload = {
            "baseline_variant": row.get("baseline_variant"),
            "active_variant": row.get("active_variant"),
            "previous_variant": row.get("previous_variant"),
            "variants": row.get("variants") or {},
        }
        return ExperimentState.from_dict(payload)

    def upsert(self, experiment_id: str, state: ExperimentState) -> None:
        with pg_connect(self._dsn) as conn:
            conn.execute(
                f"""
                INSERT INTO {self._schema}.experiments (
                    tenant_id, experiment_id, baseline_variant, active_variant,
                    previous_variant, variants
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (tenant_id, experiment_id) DO UPDATE SET
                    baseline_variant = EXCLUDED.baseline_variant,
                    active_variant = EXCLUDED.active_variant,
                    previous_variant = EXCLUDED.previous_variant,
                    variants = EXCLUDED.variants,
                    updated_at = now()
                """,
                (
                    self._tenant_id,
                    experiment_id,
                    state.baseline_variant,
                    state.active_variant,
                    state.previous_variant,
                    json.dumps(state.to_dict().get("variants", {}), ensure_ascii=True),
                ),
            )

    def _ensure_table(self) -> None:
        with pg_connect(self._dsn) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._schema}.experiments (
                    tenant_id TEXT NOT NULL,
                    experiment_id TEXT NOT NULL,
                    baseline_variant TEXT NOT NULL,
                    active_variant TEXT NOT NULL,
                    previous_variant TEXT,
                    variants JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (tenant_id, experiment_id)
                )
                """
            )


def experiment_store_from_env(root: Path) -> ExperimentStore | ExperimentStorePostgres:
    config = storage_backend_from_env()
    if config.backend != "postgres":
        return ExperimentStore(default_experiment_path(root))
    dsn = require_postgres_dsn(config, context="experiments")
    tenant_id = resolve_tenant_id(Path(root))
    return ExperimentStorePostgres(
        dsn,
        tenant_id=tenant_id,
        schema=config.postgres_schema,
    )


class ExperimentTracker:
    def __init__(
        self,
        store: ExperimentStore,
        experiment_id: str,
        variants: list[str],
        *,
        baseline_variant: str | None = None,
    ) -> None:
        if not variants:
            raise ValueError("At least one variant is required")
        self._store = store
        self._experiment_id = experiment_id
        self._variants = list(dict.fromkeys(variants))
        if not self._variants:
            raise ValueError("At least one variant is required")
        self._baseline_variant = baseline_variant or self._variants[0]
        if self._baseline_variant not in self._variants:
            raise ValueError("Baseline variant must be included in variants")
        self._ensure_state()

    @property
    def experiment_id(self) -> str:
        return self._experiment_id

    def assign_variant(self, user_id: str) -> str:
        digest = hashlib.sha256(
            f"{self._experiment_id}:{user_id}".encode("utf-8")
        ).hexdigest()
        index = int(digest, 16) % len(self._variants)
        return self._variants[index]

    def record_outcome(self, variant_id: str, success: bool) -> VariantMetrics:
        state = self._load_state()
        metrics = state.ensure_variant(variant_id)
        metrics.record(success)
        self._store.upsert(self._experiment_id, state)
        return metrics

    def metrics_for(self, variant_id: str) -> VariantMetrics:
        state = self._load_state()
        return state.ensure_variant(variant_id)

    def _ensure_state(self) -> None:
        state = self._store.get(self._experiment_id)
        if not state:
            state = ExperimentState(
                baseline_variant=self._baseline_variant,
                active_variant=self._baseline_variant,
                variants={variant: VariantMetrics() for variant in self._variants},
            )
            self._store.upsert(self._experiment_id, state)
            return
        for variant_id in self._variants:
            state.ensure_variant(variant_id)
        if not state.baseline_variant:
            state.baseline_variant = self._baseline_variant
        if not state.active_variant:
            state.active_variant = state.baseline_variant
        self._store.upsert(self._experiment_id, state)

    def _load_state(self) -> ExperimentState:
        state = self._store.get(self._experiment_id)
        if not state:
            state = ExperimentState(
                baseline_variant=self._baseline_variant,
                active_variant=self._baseline_variant,
                variants={variant: VariantMetrics() for variant in self._variants},
            )
        for variant_id in self._variants:
            state.ensure_variant(variant_id)
        return state

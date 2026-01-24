from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from skillos.experimentation import ExperimentState, ExperimentStore, VariantMetrics
from skillos.tenancy import resolve_tenant_root


def default_optimization_log_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "experiments" / "optimization.log"


@dataclass(frozen=True)
class OptimizerConfig:
    min_samples: int = 5
    win_rate_delta: float = 0.1
    rollback_delta: float = 0.1


@dataclass(frozen=True)
class OptimizationDecision:
    action: str
    reason: str
    from_variant: str | None
    to_variant: str | None
    metrics: dict[str, object]


class OptimizationLogger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def log(self, experiment_id: str, decision: OptimizationDecision) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "experiment_id": experiment_id,
            "action": decision.action,
            "reason": decision.reason,
            "from_variant": decision.from_variant,
            "to_variant": decision.to_variant,
            "metrics": decision.metrics,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


class Optimizer:
    def __init__(
        self,
        store: ExperimentStore,
        logger: OptimizationLogger,
        config: OptimizerConfig | None = None,
    ) -> None:
        self._store = store
        self._logger = logger
        self._config = config or OptimizerConfig()

    def evaluate(self, experiment_id: str) -> OptimizationDecision:
        state = self._store.get(experiment_id)
        if not state:
            raise ValueError(f"Unknown experiment: {experiment_id}")

        regression_decision = self._check_regression(state)
        if regression_decision:
            self._apply_decision(experiment_id, state, regression_decision)
            return regression_decision

        promotion_decision = self._check_promotion(state)
        if promotion_decision:
            self._apply_decision(experiment_id, state, promotion_decision)
            return promotion_decision

        return OptimizationDecision(
            action="no_action",
            reason="insufficient_evidence",
            from_variant=None,
            to_variant=None,
            metrics=self._snapshot_metrics(state),
        )

    def _check_promotion(
        self, state: ExperimentState
    ) -> OptimizationDecision | None:
        active_metrics = state.variants.get(state.active_variant)
        if not active_metrics or active_metrics.total < self._config.min_samples:
            return None

        best_variant = None
        best_metrics = None
        best_delta = 0.0
        for variant_id, metrics in state.variants.items():
            if variant_id == state.active_variant:
                continue
            if metrics.total < self._config.min_samples:
                continue
            delta = metrics.success_rate - active_metrics.success_rate
            if delta >= self._config.win_rate_delta and delta > best_delta:
                best_variant = variant_id
                best_metrics = metrics
                best_delta = delta

        if not best_variant or not best_metrics:
            return None

        return OptimizationDecision(
            action="promote",
            reason="confidence_threshold_met",
            from_variant=state.active_variant,
            to_variant=best_variant,
            metrics={
                "active": _variant_payload(state.active_variant, active_metrics),
                "candidate": _variant_payload(best_variant, best_metrics),
                "delta": round(best_delta, 4),
            },
        )

    def _check_regression(
        self, state: ExperimentState
    ) -> OptimizationDecision | None:
        if not state.previous_variant:
            return None
        active_metrics = state.variants.get(state.active_variant)
        previous_metrics = state.variants.get(state.previous_variant)
        if not active_metrics or not previous_metrics:
            return None
        if (
            active_metrics.total < self._config.min_samples
            or previous_metrics.total < self._config.min_samples
        ):
            return None
        delta = previous_metrics.success_rate - active_metrics.success_rate
        if delta < self._config.rollback_delta:
            return None
        return OptimizationDecision(
            action="rollback",
            reason="regression_detected",
            from_variant=state.active_variant,
            to_variant=state.previous_variant,
            metrics={
                "active": _variant_payload(state.active_variant, active_metrics),
                "previous": _variant_payload(state.previous_variant, previous_metrics),
                "delta": round(delta, 4),
            },
        )

    def _apply_decision(
        self,
        experiment_id: str,
        state: ExperimentState,
        decision: OptimizationDecision,
    ) -> None:
        if decision.action == "promote" and decision.to_variant:
            state.previous_variant = state.active_variant
            state.active_variant = decision.to_variant
        elif decision.action == "rollback" and decision.to_variant:
            state.active_variant = decision.to_variant
            state.previous_variant = None
        self._store.upsert(experiment_id, state)
        self._logger.log(experiment_id, decision)

    def _snapshot_metrics(self, state: ExperimentState) -> dict[str, object]:
        return {
            variant_id: _variant_payload(variant_id, metrics)
            for variant_id, metrics in state.variants.items()
        }


def _variant_payload(variant_id: str, metrics: VariantMetrics) -> dict[str, object]:
    return {
        "variant": variant_id,
        "successes": metrics.successes,
        "failures": metrics.failures,
        "total": metrics.total,
        "success_rate": round(metrics.success_rate, 4),
    }

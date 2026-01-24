from pathlib import Path

from skillos.experimentation import ExperimentStore, ExperimentTracker
from skillos.optimizer import Optimizer, OptimizerConfig, OptimizationLogger


def _record(
    tracker: ExperimentTracker, variant: str, successes: int, failures: int
) -> None:
    for _ in range(successes):
        tracker.record_outcome(variant, True)
    for _ in range(failures):
        tracker.record_outcome(variant, False)


def test_optimizer_promotes_and_rolls_back(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "experiments.json")
    tracker = ExperimentTracker(store, "skill.alpha", ["v1", "v2"], baseline_variant="v1")

    _record(tracker, "v1", successes=3, failures=1)
    _record(tracker, "v2", successes=4, failures=0)

    config = OptimizerConfig(min_samples=4, win_rate_delta=0.1, rollback_delta=0.2)
    optimizer = Optimizer(store, OptimizationLogger(tmp_path / "decisions.log"), config)

    decision = optimizer.evaluate("skill.alpha")
    assert decision.action == "promote"

    state = store.get("skill.alpha")
    assert state is not None
    assert state.active_variant == "v2"

    _record(tracker, "v2", successes=0, failures=4)
    decision = optimizer.evaluate("skill.alpha")
    assert decision.action == "rollback"

    state = store.get("skill.alpha")
    assert state is not None
    assert state.active_variant == "v1"

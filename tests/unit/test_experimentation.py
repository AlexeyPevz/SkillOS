from pathlib import Path

from skillos.experimentation import ExperimentStore, ExperimentTracker


def test_ab_assignment_stable_and_metrics_recorded(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "experiments.json")
    tracker = ExperimentTracker(
        store,
        "skill.alpha",
        ["v1", "v2"],
        baseline_variant="v1",
    )

    first = tracker.assign_variant("user-1")
    second = tracker.assign_variant("user-1")
    assert first == second

    tracker.record_outcome("v1", True)
    tracker.record_outcome("v2", False)

    state = store.get("skill.alpha")
    assert state is not None
    assert state.variants["v1"].successes == 1
    assert state.variants["v2"].failures == 1

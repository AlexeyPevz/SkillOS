import json
from pathlib import Path

import yaml

from skillos.composition import activate_composed_skill, compose_skill
from skillos.skills.models import SkillMetadata
from skillos.skills.registry import SkillRegistry


def _ensure_package(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    init_file = path / "__init__.py"
    if not init_file.exists():
        init_file.write_text("", encoding="utf-8")


def _write_skill(root: Path, skill_id: str, implementation: str) -> None:
    domain, name = skill_id.split("/", 1)
    metadata_dir = root / "metadata" / domain
    implementation_dir = root / "implementations" / domain
    _ensure_package(root / "implementations")
    _ensure_package(implementation_dir)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    metadata = SkillMetadata(
        id=skill_id,
        name=name.replace("_", " ").title(),
        description=f"Skill for {skill_id}",
        version="0.1.0",
        entrypoint=f"implementations.{domain}.{name}:run",
        tags=[domain],
    )
    metadata_path = metadata_dir / f"{name}.yaml"
    metadata_path.write_text(
        yaml.safe_dump(metadata.model_dump(), sort_keys=False),
        encoding="utf-8",
    )
    implementation_path = implementation_dir / f"{name}.py"
    implementation_path.write_text(implementation, encoding="utf-8")


def _timed_implementation(name: str) -> str:
    return (
        "import os\n"
        "import time\n"
        "from pathlib import Path\n"
        "\n"
        "def run(payload='ok'):\n"
        f"    name = '{name}'\n"
        "    timing_dir = os.getenv('SKILLOS_TIMING_DIR')\n"
        "    start = time.perf_counter()\n"
        "    if timing_dir:\n"
        "        path = Path(timing_dir)\n"
        "        path.mkdir(parents=True, exist_ok=True)\n"
        "        (path / f'{name}_start.txt').write_text(str(start), encoding='utf-8')\n"
        "    time.sleep(0.2)\n"
        "    end = time.perf_counter()\n"
        "    if timing_dir:\n"
        "        path = Path(timing_dir)\n"
        "        (path / f'{name}_end.txt').write_text(str(end), encoding='utf-8')\n"
        "    return f\"{payload}-{name}\"\n"
    )


def _read_time(timing_dir: Path, name: str, suffix: str) -> float:
    return float((timing_dir / f"{name}_{suffix}.txt").read_text(encoding="utf-8"))


def test_parallel_composition_executes_concurrently_and_logs(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "skills"
    timing_dir = tmp_path / "timings"
    monkeypatch.setenv("SKILLOS_TIMING_DIR", str(timing_dir))
    monkeypatch.setenv("SKILLOS_PARALLEL_LIMIT", "2")

    _write_skill(root, "travel/alpha", _timed_implementation("alpha"))
    _write_skill(root, "travel/beta", _timed_implementation("beta"))
    _write_skill(root, "travel/gamma", _timed_implementation("gamma"))

    compose_skill(
        root,
        "travel/plan_trip",
        [["travel/alpha", "travel/beta", "travel/gamma"]],
    )
    activation = activate_composed_skill(
        root,
        "travel/plan_trip",
        approval_status="approved",
        require_tests=False,
    )
    assert activation.activated is True

    registry = SkillRegistry(root)
    registry.load_all()
    output = registry.execute("travel/plan_trip", payload="start")

    assert "start-alpha" in output
    assert "start-beta" in output
    assert "start-gamma" in output

    start_times = {
        "alpha": _read_time(timing_dir, "alpha", "start"),
        "beta": _read_time(timing_dir, "beta", "start"),
        "gamma": _read_time(timing_dir, "gamma", "start"),
    }
    end_times = {
        "alpha": _read_time(timing_dir, "alpha", "end"),
        "beta": _read_time(timing_dir, "beta", "end"),
        "gamma": _read_time(timing_dir, "gamma", "end"),
    }

    sorted_starts = sorted(start_times.values())
    assert sorted_starts[1] - sorted_starts[0] < 0.1
    latest_start = sorted_starts[-1]
    earliest_end = sorted(end_times.values())[0]
    assert latest_start >= earliest_end - 0.02

    log_path = root / "logs" / "execution.log"
    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    step_events = [entry for entry in entries if entry["event"] == "composition_step"]
    assert len(step_events) == 3
    ordered_steps = sorted(step_events, key=lambda entry: entry["order"])
    assert [entry["order"] for entry in ordered_steps] == [0, 1, 2]
    assert [entry["step_id"] for entry in ordered_steps] == [
        "travel/alpha",
        "travel/beta",
        "travel/gamma",
    ]
    assert all(entry["duration_ms"] > 0 for entry in step_events)

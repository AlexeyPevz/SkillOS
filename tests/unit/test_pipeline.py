import json
from pathlib import Path

import pytest
import yaml

from skillos.pipeline import PipelineRunner
from skillos.routing import to_public_id
from skillos.skills.models import SkillMetadata


def _ensure_package(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    init_file = path / "__init__.py"
    if not init_file.exists():
        init_file.write_text("", encoding="utf-8")


def _write_skill(
    root: Path,
    skill_id: str,
    implementation: str,
    *,
    deprecated: bool = False,
    deprecation_reason: str | None = None,
    replacement_id: str | None = None,
) -> None:
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
        deprecated=deprecated,
        deprecation_reason=deprecation_reason,
        replacement_id=replacement_id,
    )
    metadata_path = metadata_dir / f"{name}.yaml"
    metadata_path.write_text(
        yaml.safe_dump(
            metadata.model_dump(exclude_defaults=True, exclude_none=True),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    implementation_path = implementation_dir / f"{name}.py"
    implementation_path.write_text(implementation, encoding="utf-8")


def test_pipeline_executes_sequentially_and_logs(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(
        root,
        "ops/first",
        "def run(payload='ok'):\n    return f'{payload}-one'\n",
    )
    _write_skill(
        root,
        "ops/second",
        "def run(payload='ok'):\n    return f'{payload}-two'\n",
    )

    runner = PipelineRunner(root)
    result = runner.run(["ops/first", "ops/second"], payload="start")
    assert result.status == "success"
    assert result.output == "start-one-two"

    log_path = root / "logs" / "execution.log"
    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    pipeline_events = [
        entry for entry in entries if entry.get("event") == "pipeline_step"
    ]
    assert [entry["order"] for entry in pipeline_events] == [0, 1]
    assert [entry["step_id"] for entry in pipeline_events] == [
        to_public_id("ops/first"),
        to_public_id("ops/second"),
    ]
    assert all(entry["duration_ms"] >= 0 for entry in pipeline_events)


def test_pipeline_parallel_group_combines_outputs(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(
        root,
        "ops/alpha",
        "def run(payload='ok'):\n    return f'{payload}-alpha'\n",
    )
    _write_skill(
        root,
        "ops/beta",
        "def run(payload='ok'):\n    return f'{payload}-beta'\n",
    )

    runner = PipelineRunner(root)
    result = runner.run(["ops/alpha|ops/beta"], payload="start")
    assert result.status == "success"
    assert result.output.splitlines() == ["start-alpha", "start-beta"]


def test_pipeline_warns_on_deprecated_skill(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(
        root,
        "ops/legacy",
        "def run(payload='ok'):\n    return f'{payload}-legacy'\n",
        deprecated=True,
        deprecation_reason="use ops/modern",
        replacement_id="ops/modern",
    )

    runner = PipelineRunner(root)
    result = runner.run(["ops/legacy"], payload="start")
    assert result.status == "success"
    assert result.warnings
    warning = result.warnings[0]
    assert warning["code"] == "deprecated_skill"
    assert warning["replacement_id"] == "ops/modern"


@pytest.mark.asyncio
async def test_pipeline_async_parallel_group_combines_outputs(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(
        root,
        "ops/alpha",
        "import asyncio\n"
        "async def run(payload='ok'):\n"
        "    await asyncio.sleep(0)\n"
        "    return f'{payload}-alpha'\n",
    )
    _write_skill(
        root,
        "ops/beta",
        "import asyncio\n"
        "async def run(payload='ok'):\n"
        "    await asyncio.sleep(0)\n"
        "    return f'{payload}-beta'\n",
    )

    runner = PipelineRunner(root)
    result = await runner.run_async(["ops/alpha|ops/beta"], payload="start")
    assert result.status == "success"
    assert result.output.splitlines() == ["start-alpha", "start-beta"]

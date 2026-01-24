from pathlib import Path

import pytest
import yaml

from skillos.composition import CompositionError, compose_skill
from skillos.skills.models import SkillMetadata


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


def test_composition_rejects_cycles(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "travel/search_flights", "def run(payload='ok'):\n    return payload\n")

    with pytest.raises(CompositionError):
        compose_skill(root, "travel/plan_trip", ["travel/plan_trip"])


def test_composition_rejects_invalid_contract(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(
        root,
        "finance/invalid",
        "def run(payload, extra):\n    return payload\n",
    )

    with pytest.raises(CompositionError):
        compose_skill(root, "finance/reporting", ["finance/invalid"])


def test_composition_accepts_parallel_groups(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "travel/first", "def run(payload='ok'):\n    return payload\n")
    _write_skill(root, "travel/second", "def run(payload='ok'):\n    return payload\n")
    _write_skill(root, "travel/third", "def run(payload='ok'):\n    return payload\n")

    spec = compose_skill(
        root,
        "travel/plan_trip",
        ["travel/first", ["travel/second", "travel/third"]],
    )

    assert spec.steps == [["travel/first"], ["travel/second", "travel/third"]]


def test_composition_rejects_invalid_parallel_group(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "travel/first", "def run(payload='ok'):\n    return payload\n")

    with pytest.raises(CompositionError):
        compose_skill(root, "travel/plan_trip", ["travel/first", [""]])

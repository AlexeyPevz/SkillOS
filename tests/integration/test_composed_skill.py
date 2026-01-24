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


def test_composed_skill_executes_and_versions(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(
        root,
        "travel/first",
        "def run(payload='ok'):\n    return f'{payload}-one'\n",
    )
    _write_skill(
        root,
        "travel/second",
        "def run(payload='ok'):\n    return f'{payload}-two'\n",
    )

    spec = compose_skill(root, "travel/plan_trip", ["travel/first", "travel/second"])
    assert spec.version == "0.1.0"
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
    assert output == "start-one-two"

    updated = compose_skill(root, "travel/plan_trip", ["travel/second", "travel/first"])
    assert updated.version == "0.1.1"
    activation = activate_composed_skill(
        root,
        "travel/plan_trip",
        approval_status="approved",
        require_tests=False,
    )
    assert activation.activated is True
    output = registry.execute("travel/plan_trip", payload="start")
    assert output == "start-two-one"

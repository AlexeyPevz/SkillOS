from pathlib import Path

import yaml

from skillos.execution import execute_plan
from skillos.execution_planner import build_execution_plan
from skillos.skills.registry import SkillRegistry


def _write_write_skill(root: Path, skill_id: str) -> Path:
    domain, name = skill_id.split("/", 1)
    metadata_dir = root / "metadata" / domain
    implementation_dir = root / "implementations" / domain
    metadata_dir.mkdir(parents=True, exist_ok=True)
    implementation_dir.mkdir(parents=True, exist_ok=True)

    for package_dir in [root / "implementations", implementation_dir]:
        init_file = package_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")

    metadata = {
        "id": skill_id,
        "name": "Write File",
        "description": "Writes to disk",
        "version": "0.1.0",
        "entrypoint": f"implementations.{domain}.{name}:run",
        "tags": [domain],
    }
    metadata_file = metadata_dir / f"{name}.yaml"
    metadata_file.write_text(
        yaml.safe_dump(metadata, sort_keys=False),
        encoding="utf-8",
    )

    implementation_file = implementation_dir / f"{name}.py"
    implementation_file.write_text(
        "from pathlib import Path\n\n"
        "def run(payload: str = \"ok\") -> str:\n"
        "    output_path = Path(__file__).with_name(\"output.txt\")\n"
        "    output_path.write_text(payload, encoding=\"utf-8\")\n"
        "    return \"written\"\n",
        encoding="utf-8",
    )
    return implementation_dir / "output.txt"


def test_dry_run_prevents_write_and_returns_preview(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill_id = "demo/write_file"
    output_path = _write_write_skill(root, skill_id)
    registry = SkillRegistry(root)
    registry.load_all()
    plan = build_execution_plan(skill_id, skill_id, "preview payload")

    result = execute_plan(registry, plan, dry_run=True)

    assert result.executed is False
    assert result.output is None
    assert result.preview is not None
    assert result.preview.plan_id == plan.plan_id
    assert result.preview.affected_entities == [skill_id]
    assert not output_path.exists()

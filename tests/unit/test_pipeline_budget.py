import json
from pathlib import Path

import yaml

from skillos.authorization import default_permissions_path
from skillos.budget import default_budget_path
from skillos.pipeline import PipelineRunner
from skillos.skills.models import SkillMetadata


def _ensure_package(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    init_file = path / "__init__.py"
    if not init_file.exists():
        init_file.write_text("", encoding="utf-8")


def _write_skill(root: Path, skill_id: str) -> None:
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
        yaml.safe_dump(metadata.model_dump(exclude_defaults=True), sort_keys=False),
        encoding="utf-8",
    )
    implementation_path = implementation_dir / f"{name}.py"
    implementation_path.write_text(
        "def run(payload='ok'):\n    return payload\n",
        encoding="utf-8",
    )


def test_pipeline_permission_denied_does_not_charge_budget(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "ops/first")

    permissions_path = default_permissions_path(root)
    permissions_path.parent.mkdir(parents=True, exist_ok=True)
    permissions_path.write_text(
        json.dumps(
            {
                "roles": {"viewer": []},
                "policies": [
                    {
                        "skill_id": "ops/first",
                        "required_permissions": ["ops:run"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    runner = PipelineRunner(root)
    result = runner.run(["ops/first"], payload="ok", role="viewer")

    assert result.status == "blocked"
    assert result.reason == "permission_denied"

    budget_path = default_budget_path(root)
    if budget_path.exists():
        payload = json.loads(budget_path.read_text(encoding="utf-8"))
        assert payload.get("daily", {}) == {}
        assert payload.get("monthly", {}) == {}

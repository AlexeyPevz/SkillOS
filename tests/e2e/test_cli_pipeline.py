from pathlib import Path

import yaml
from click.testing import CliRunner

from skillos.cli import cli
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


def test_cli_pipeline_run_executes_steps() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        root = Path("skills")
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

        result = runner.invoke(
            cli,
            [
                "pipeline",
                "run",
                "--root",
                str(root),
                "--step",
                "ops/first",
                "--step",
                "ops/second",
                "--payload",
                "start",
            ],
        )
        assert result.exit_code == 0
        assert result.output.strip() == "start-one-two"

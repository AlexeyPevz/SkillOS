from __future__ import annotations

from pathlib import Path

import yaml

from skillos.skills.errors import SkillValidationError
from skillos.skills.models import SkillMetadata


def scaffold_skill(skill_id: str, root: Path) -> tuple[Path, Path]:
    domain, name = _parse_skill_id(skill_id)
    root_path = Path(root)
    metadata_path = root_path / "metadata" / domain
    implementation_path = root_path / "implementations" / domain

    metadata_path.mkdir(parents=True, exist_ok=True)
    implementation_path.mkdir(parents=True, exist_ok=True)
    _ensure_package(root_path / "implementations")
    _ensure_package(implementation_path)

    metadata_file = metadata_path / f"{name}.yaml"
    implementation_file = implementation_path / f"{name}.py"

    if metadata_file.exists() or implementation_file.exists():
        raise FileExistsError("Skill already exists")

    entrypoint = f"implementations.{domain}.{name}:run"
    metadata = SkillMetadata(
        id=skill_id,
        name=name.replace("_", " ").title(),
        description=f"Auto-generated skill for {skill_id}",
        version="0.1.0",
        entrypoint=entrypoint,
        tags=[domain],
    )
    metadata_file.write_text(
        yaml.safe_dump(
            metadata.model_dump(exclude_defaults=True, exclude_none=True),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    implementation_file.write_text(_implementation_template(skill_id), encoding="utf-8")
    return metadata_file, implementation_file


def _parse_skill_id(skill_id: str) -> tuple[str, str]:
    if "/" not in skill_id:
        raise SkillValidationError("Skill id must be in 'domain/name' format")
    domain, name = skill_id.split("/", 1)
    if not domain or not name:
        raise SkillValidationError("Skill id must be in 'domain/name' format")
    return domain, name


def _ensure_package(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    init_file = path / "__init__.py"
    if not init_file.exists():
        init_file.write_text("", encoding="utf-8")


def _implementation_template(skill_id: str) -> str:
    return (
        "def run(payload: str = \"ok\") -> str:\n"
        f"    return \"{skill_id} executed\"\n"
    )

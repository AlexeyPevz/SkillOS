from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skillos.skills.errors import SkillValidationError
from skillos.skills.loader import load_skill_file
from skillos.skills.registry import resolve_entrypoint


@dataclass(frozen=True)
class SkillValidationIssue:
    path: Path
    category: str
    message: str
    skill_id: str | None = None


def validate_skills(
    root: Path, *, check_entrypoints: bool = True
) -> list[SkillValidationIssue]:
    root_path = Path(root)
    metadata_path = root_path / "metadata"
    if not metadata_path.exists():
        return []

    issues: list[SkillValidationIssue] = []
    for file_path in _iter_skill_files(metadata_path):
        try:
            metadata = load_skill_file(file_path)
        except SkillValidationError as exc:
            issues.append(
                SkillValidationIssue(
                    path=file_path,
                    category="metadata",
                    message=str(exc),
                )
            )
            continue

        if not check_entrypoints:
            continue

        try:
            resolve_entrypoint(metadata.entrypoint, root_path)
        except Exception as exc:  # pragma: no cover - defensive
            issues.append(
                SkillValidationIssue(
                    path=file_path,
                    category="entrypoint",
                    message=_format_entrypoint_error(exc),
                    skill_id=metadata.id,
                )
            )
    return issues


def _iter_skill_files(metadata_path: Path) -> list[Path]:
    yaml_files = list(metadata_path.rglob("*.yaml"))
    yml_files = list(metadata_path.rglob("*.yml"))
    return sorted(yaml_files + yml_files)


def _format_entrypoint_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{exc.__class__.__name__}: {message}"
    return exc.__class__.__name__

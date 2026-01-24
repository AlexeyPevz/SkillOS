from __future__ import annotations

from pathlib import Path

import yaml

from skillos.routing import to_internal_id
from skillos.skills.errors import SkillValidationError
from skillos.skills.models import SkillMetadata
from skillos.skills.registry import SkillRegistry


def deprecate_skill(
    root: Path,
    skill_id: str,
    *,
    reason: str | None = None,
    replacement_id: str | None = None,
) -> Path:
    reason = _normalize_optional(reason)
    replacement_id = _normalize_optional(replacement_id)
    if not reason and not replacement_id:
        raise ValueError("deprecation_reason_or_replacement_required")

    raw, metadata_path = _load_metadata(root, skill_id)
    raw["deprecated"] = True
    if reason is not None:
        raw["deprecation_reason"] = reason
    if replacement_id is not None:
        raw["replacement_id"] = replacement_id

    _validate_metadata(raw)
    _write_metadata(metadata_path, raw)
    return metadata_path


def undeprecate_skill(root: Path, skill_id: str) -> Path:
    raw, metadata_path = _load_metadata(root, skill_id)
    raw["deprecated"] = False
    raw.pop("deprecation_reason", None)
    raw.pop("replacement_id", None)

    _validate_metadata(raw)
    _write_metadata(metadata_path, raw)
    return metadata_path


def _load_metadata(root: Path, skill_id: str) -> tuple[dict[str, object], Path]:
    registry = SkillRegistry(root)
    records = registry.load_all()
    internal_id = to_internal_id(skill_id.strip())
    record = records.get(internal_id)
    if not record:
        raise FileNotFoundError(f"Unknown skill: {skill_id}")

    metadata_path = record.source
    raw = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SkillValidationError("Skill YAML must be a mapping")
    return raw, metadata_path


def _validate_metadata(raw: dict[str, object]) -> None:
    try:
        SkillMetadata.model_validate(raw)
    except Exception as exc:
        raise SkillValidationError(str(exc)) from exc


def _write_metadata(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def build_deprecation_warning(
    skill_id: str,
    metadata: SkillMetadata,
) -> dict[str, object]:
    message = f"Skill {skill_id} is deprecated"
    if metadata.replacement_id:
        message = f"{message}; use {metadata.replacement_id}"
    warning: dict[str, object] = {
        "code": "deprecated_skill",
        "skill_id": skill_id,
        "message": message,
    }
    if metadata.deprecation_reason:
        warning["deprecation_reason"] = metadata.deprecation_reason
    if metadata.replacement_id:
        warning["replacement_id"] = metadata.replacement_id
    return warning

from pathlib import Path

import yaml
from pydantic import ValidationError

from skillos.skills.errors import SkillValidationError
from skillos.skills.models import SkillMetadata

_SKILL_CACHE: dict[Path, tuple[int, SkillMetadata]] = {}


def load_skill_file(path: Path) -> SkillMetadata:
    path = Path(path)
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        _SKILL_CACHE.pop(path, None)
        raise

    cached = _SKILL_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise SkillValidationError(f"Unable to read skill YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise SkillValidationError("Skill YAML must be a mapping")

    try:
        metadata = SkillMetadata.model_validate(raw)
    except ValidationError as exc:
        raise SkillValidationError(_format_validation_errors(exc)) from exc
    _SKILL_CACHE[path] = (mtime, metadata)
    return metadata


def _format_validation_errors(error: ValidationError) -> str:
    parts: list[str] = []
    for item in error.errors():
        loc = ".".join(str(piece) for piece in item.get("loc", [])) or "skill"
        parts.append(f"{loc}: {item.get('msg')}")
    return "; ".join(parts)

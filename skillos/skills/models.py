from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator


_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


class SkillMetadata(BaseModel):
    id: str = Field(..., min_length=3)
    name: str
    description: str
    version: str
    entrypoint: str
    tags: list[str] = Field(default_factory=list)
    deprecated: bool = False
    deprecation_reason: str | None = None
    replacement_id: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if "/" not in value or value.startswith("/") or value.endswith("/"):
            raise ValueError("id must be in 'domain/name' format")
        return value

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str) -> str:
        if ":" not in value:
            raise ValueError("entrypoint must be in 'module:function' format")
        return value

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not _SEMVER_RE.match(value):
            raise ValueError("version must follow semver, e.g. 1.0.0")
        return value

    @field_validator("replacement_id")
    @classmethod
    def validate_replacement_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("replacement_id must be in 'domain/name' format")
        if "/" not in cleaned or cleaned.startswith("/") or cleaned.endswith("/"):
            raise ValueError("replacement_id must be in 'domain/name' format")
        return cleaned

    @model_validator(mode="after")
    def validate_deprecation(self) -> "SkillMetadata":
        if self.deprecated and not (self.deprecation_reason or self.replacement_id):
            raise ValueError(
                "deprecated skills must include deprecation_reason or replacement_id"
            )
        return self

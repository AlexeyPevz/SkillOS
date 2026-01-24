from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Mapping


_TENANT_ENV = "SKILLOS_TENANT_ID"
_TENANT_DIR = "tenants"
_TENANT_RE = re.compile(r"[^A-Za-z0-9_-]+")


def normalize_tenant_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    normalized = _TENANT_RE.sub("-", cleaned)
    normalized = normalized.strip("-_")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized or None


def tenant_id_from_env(env: Mapping[str, str] | None = None) -> str | None:
    env_map = env or os.environ
    return normalize_tenant_id(env_map.get(_TENANT_ENV))


def resolve_tenant_root(root: Path | str, tenant_id: str | None = None) -> Path:
    root_path = Path(root)
    if tenant_id is not None:
        resolved = normalize_tenant_id(tenant_id)
    else:
        resolved = tenant_id_from_env()
    if not resolved:
        return root_path
    if _has_tenant_segment(root_path, resolved):
        return root_path
    if root_path.parts and root_path.parts[-1] == _TENANT_DIR:
        return root_path / resolved
    return root_path / _TENANT_DIR / resolved


def _has_tenant_segment(root: Path, tenant_id: str) -> bool:
    parts = root.parts
    for index in range(len(parts) - 1):
        if parts[index] == _TENANT_DIR and parts[index + 1] == tenant_id:
            return True
    return False


def tenant_id_from_path(root: Path | str) -> str | None:
    root_path = Path(root)
    parts = root_path.parts
    for index in range(len(parts) - 1):
        if parts[index] == _TENANT_DIR:
            candidate = normalize_tenant_id(parts[index + 1])
            return candidate
    return None

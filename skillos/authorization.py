from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
import json
from pathlib import Path

from skillos.tenancy import resolve_tenant_root

PERMISSION_GRANTED_POLICY_ID = "permission_granted"
PERMISSION_DENIED_POLICY_ID = "permission_denied"
PERMISSION_NOT_REQUIRED_POLICY_ID = "permission_not_required"
ABAC_DENIED_POLICY_ID = "abac_denied"


def default_permissions_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "policies" / "permission_policies.json"


@dataclass(frozen=True)
class PermissionPolicy:
    skill_id: str
    required_permissions: list[str]

    def matches(self, skill_id: str) -> bool:
        return fnmatch(skill_id, self.skill_id)


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    policy_id: str
    role: str | None
    skill_id: str
    required_permissions: list[str]
    missing_permissions: list[str]


@dataclass(frozen=True)
class AbacPolicy:
    skill_id: str
    effect: str = "allow"
    conditions: dict[str, list[str]] | None = None
    policy_id: str | None = None

    def matches(self, skill_id: str) -> bool:
        return fnmatch(skill_id, self.skill_id)

    def applies(self, attributes: dict[str, object]) -> bool:
        conditions = self.conditions or {}
        for key, values in conditions.items():
            if not _match_condition(attributes.get(key), values):
                return False
        return True


class PermissionChecker:
    def __init__(
        self,
        policies: list[PermissionPolicy] | None = None,
        role_permissions: dict[str, list[str]] | None = None,
        abac_policies: list[AbacPolicy] | None = None,
    ) -> None:
        self._policies = policies or []
        self._role_permissions = role_permissions or {}
        self._abac_policies = abac_policies or []

    @classmethod
    def from_path(cls, path: Path) -> "PermissionChecker":
        policies, role_permissions, abac_policies = load_permission_config(path)
        return cls(
            policies=policies,
            role_permissions=role_permissions,
            abac_policies=abac_policies,
        )

    def authorize(
        self,
        skill_id: str,
        role: str | None,
        *,
        skill_tags: list[str] | None = None,
        attributes: dict[str, object] | None = None,
    ) -> PermissionDecision:
        policy = self._match_policy(skill_id)
        required = policy.required_permissions if policy else []
        if not required:
            decision = PermissionDecision(
                allowed=True,
                policy_id=PERMISSION_NOT_REQUIRED_POLICY_ID,
                role=role,
                skill_id=skill_id,
                required_permissions=required,
                missing_permissions=[],
            )
            return self._apply_abac(decision, role, skill_id, skill_tags, attributes)

        granted = self._role_permissions.get(role or "", [])
        missing = _missing_permissions(granted, required)
        allowed = not missing
        policy_id = (
            PERMISSION_GRANTED_POLICY_ID if allowed else PERMISSION_DENIED_POLICY_ID
        )
        decision = PermissionDecision(
            allowed=allowed,
            policy_id=policy_id,
            role=role,
            skill_id=skill_id,
            required_permissions=required,
            missing_permissions=missing,
        )
        if not decision.allowed:
            return decision
        return self._apply_abac(decision, role, skill_id, skill_tags, attributes)

    def _match_policy(self, skill_id: str) -> PermissionPolicy | None:
        for policy in self._policies:
            if policy.matches(skill_id):
                return policy
        return None

    def _apply_abac(
        self,
        decision: PermissionDecision,
        role: str | None,
        skill_id: str,
        skill_tags: list[str] | None,
        attributes: dict[str, object] | None,
    ) -> PermissionDecision:
        if not self._abac_policies:
            return decision
        payload = {
            "role": role,
            "tags": skill_tags or [],
            "skill_id": skill_id,
        }
        if attributes:
            payload.update(attributes)
        abac_decision = _evaluate_abac(self._abac_policies, skill_id, payload)
        if abac_decision is None:
            return decision
        if abac_decision["allowed"]:
            return decision
        return PermissionDecision(
            allowed=False,
            policy_id=abac_decision["policy_id"],
            role=role,
            skill_id=skill_id,
            required_permissions=decision.required_permissions,
            missing_permissions=[],
        )


def load_permission_config(
    path: Path,
) -> tuple[list[PermissionPolicy], dict[str, list[str]], list[AbacPolicy]]:
    if not path.exists():
        return [], {}, []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return [], {}, []

    role_permissions = _load_role_permissions(raw.get("roles", {}))
    policies = _load_permission_policies(raw.get("policies", []))
    abac_policies = _load_abac_policies(raw.get("abac_policies", []))
    return policies, role_permissions, abac_policies


def _load_role_permissions(raw_roles: object) -> dict[str, list[str]]:
    if not isinstance(raw_roles, dict):
        return {}
    role_permissions: dict[str, list[str]] = {}
    for role, permissions in raw_roles.items():
        role_name = str(role).strip()
        if not role_name:
            continue
        normalized = _normalize_permissions(permissions)
        if normalized:
            role_permissions[role_name] = normalized
    return role_permissions


def _load_permission_policies(raw_policies: object) -> list[PermissionPolicy]:
    if isinstance(raw_policies, dict):
        raw_policies = raw_policies.get("policies", [])
    if not isinstance(raw_policies, list):
        return []

    policies: list[PermissionPolicy] = []
    for item in raw_policies:
        if not isinstance(item, dict):
            continue
        skill_id = str(item.get("skill_id", "")).strip()
        if not skill_id:
            continue
        required = _normalize_permissions(
            item.get("required_permissions", item.get("permissions", []))
        )
        policies.append(
            PermissionPolicy(skill_id=skill_id, required_permissions=required)
        )
    return policies


def _normalize_permissions(raw: object) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    normalized = [str(item).strip() for item in raw]
    return [item for item in normalized if item]


def _missing_permissions(granted: list[str], required: list[str]) -> list[str]:
    missing: list[str] = []
    for requirement in required:
        if not any(fnmatch(requirement, permission) for permission in granted):
            missing.append(requirement)
    return missing


def _normalize_condition_values(raw: object) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    normalized = [str(item).strip() for item in raw]
    return [item for item in normalized if item]


def _load_abac_policies(raw_policies: object) -> list[AbacPolicy]:
    if not isinstance(raw_policies, list):
        return []
    policies: list[AbacPolicy] = []
    for item in raw_policies:
        if not isinstance(item, dict):
            continue
        skill_id = str(item.get("skill_id", "")).strip()
        if not skill_id:
            continue
        effect = str(item.get("effect", "allow")).strip().lower()
        if effect not in {"allow", "deny"}:
            continue
        conditions_raw = item.get("conditions", {})
        if not isinstance(conditions_raw, dict):
            conditions_raw = {}
        conditions = {
            key: _normalize_condition_values(value)
            for key, value in conditions_raw.items()
        }
        policies.append(
            AbacPolicy(
                skill_id=skill_id,
                effect=effect,
                conditions=conditions,
                policy_id=item.get("policy_id"),
            )
        )
    return policies


def _match_condition(value: object, expected: list[str]) -> bool:
    if not expected:
        return True
    if isinstance(value, list):
        values = [str(item) for item in value]
        return any(entry in expected for entry in values)
    if value is None:
        return False
    return str(value) in expected


def _evaluate_abac(
    policies: list[AbacPolicy],
    skill_id: str,
    attributes: dict[str, object],
) -> dict[str, object] | None:
    allowed_policy: AbacPolicy | None = None
    for policy in policies:
        if not policy.matches(skill_id):
            continue
        if not policy.applies(attributes):
            continue
        if policy.effect == "deny":
            return {
                "allowed": False,
                "policy_id": policy.policy_id or ABAC_DENIED_POLICY_ID,
            }
        allowed_policy = policy
    if allowed_policy:
        return {
            "allowed": True,
            "policy_id": allowed_policy.policy_id or "abac_allowed",
        }
    return None

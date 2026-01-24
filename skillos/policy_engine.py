from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
import json
from pathlib import Path

from skillos.risk_scorer import HIGH_RISK_THRESHOLD, RiskAssessment
from skillos.tenancy import resolve_tenant_root


def default_policy_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "policies" / "approval_policies.json"


@dataclass(frozen=True)
class ApprovalPolicy:
    skill_id: str
    requires_approval: bool = True
    policy_id: str | None = None

    def matches(self, skill_id: str) -> bool:
        return fnmatch(skill_id, self.skill_id)


@dataclass(frozen=True)
class ApprovalRequirement:
    required: bool
    policy_id: str
    reasons: list[str]
    risk_score: int
    risk_level: str


class PolicyEngine:
    def __init__(
        self,
        policies: list[ApprovalPolicy] | None = None,
        high_risk_threshold: int = HIGH_RISK_THRESHOLD,
    ) -> None:
        self._policies = policies or []
        self._high_risk_threshold = high_risk_threshold

    @classmethod
    def from_path(
        cls, path: Path, high_risk_threshold: int = HIGH_RISK_THRESHOLD
    ) -> "PolicyEngine":
        return cls(load_approval_policies(path), high_risk_threshold)

    def approval_requirement(
        self, skill_id: str, risk: RiskAssessment
    ) -> ApprovalRequirement:
        reasons: list[str] = []
        policy_id = "no_approval_required"
        required = False
        policy = self._match_policy(skill_id)
        if policy and policy.requires_approval:
            required = True
            reasons.append("skill_policy")
            policy_id = policy.policy_id or "skill_policy"

        if risk.score >= self._high_risk_threshold:
            required = True
            reasons.append("high_risk")
            if not policy or not policy.requires_approval:
                policy_id = "high_risk"

        return ApprovalRequirement(
            required=required,
            policy_id=policy_id,
            reasons=reasons,
            risk_score=risk.score,
            risk_level=risk.level,
        )

    def _match_policy(self, skill_id: str) -> ApprovalPolicy | None:
        for policy in self._policies:
            if policy.matches(skill_id):
                return policy
        return None


def load_approval_policies(path: Path) -> list[ApprovalPolicy]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw_policies = raw.get("policies", [])
    elif isinstance(raw, list):
        raw_policies = raw
    else:
        return []

    policies: list[ApprovalPolicy] = []
    for item in raw_policies:
        if not isinstance(item, dict):
            continue
        skill_id = str(item.get("skill_id", "")).strip()
        if not skill_id:
            continue
        requires_approval = bool(item.get("requires_approval", True))
        policy_id = item.get("policy_id")
        policies.append(
            ApprovalPolicy(
                skill_id=skill_id,
                requires_approval=requires_approval,
                policy_id=policy_id,
            )
        )
    return policies

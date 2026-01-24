from __future__ import annotations

from dataclasses import dataclass

from skillos.approval_gate import ApprovalDecision, ApprovalGate
from skillos.policy_engine import ApprovalRequirement, PolicyEngine
from skillos.risk_scorer import RiskAssessment, RiskScorer


@dataclass(frozen=True)
class ExecutionDecision:
    risk: RiskAssessment
    requirement: ApprovalRequirement
    approval: ApprovalDecision


class ToolWrapper:
    def __init__(
        self,
        risk_scorer: RiskScorer | None = None,
        policy_engine: PolicyEngine | None = None,
        approval_gate: ApprovalGate | None = None,
    ) -> None:
        self._risk_scorer = risk_scorer or RiskScorer()
        self._policy_engine = policy_engine or PolicyEngine()
        self._approval_gate = approval_gate or ApprovalGate()

    def authorize(
        self,
        skill_id: str,
        payload: str,
        approval_status: str | None = None,
        approval_token: str | None = None,
    ) -> ExecutionDecision:
        risk = self._risk_scorer.assess(payload, skill_id)
        requirement = self._policy_engine.approval_requirement(skill_id, risk)
        approval = self._approval_gate.check(
            requirement, approval_status, approval_token
        )
        return ExecutionDecision(
            risk=risk,
            requirement=requirement,
            approval=approval,
        )

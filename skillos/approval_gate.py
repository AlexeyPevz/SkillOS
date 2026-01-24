from __future__ import annotations

from dataclasses import dataclass
import os

from skillos.policy_engine import ApprovalRequirement


def approval_token_from_env() -> str | None:
    return os.getenv("SKILLOS_APPROVAL_TOKEN")


@dataclass(frozen=True)
class ApprovalDecision:
    allowed: bool
    policy_id: str
    status: str


class ApprovalGate:
    def __init__(self, required_token: str | None = None) -> None:
        self._required_token = required_token

    def check(
        self,
        requirement: ApprovalRequirement,
        approval_status: str | None,
        approval_token: str | None = None,
    ) -> ApprovalDecision:
        if not requirement.required:
            return ApprovalDecision(
                allowed=True,
                policy_id="approval_not_required",
                status="not_required",
            )
        if approval_status == "approved":
            if self._required_token and approval_token != self._required_token:
                return ApprovalDecision(
                    allowed=False,
                    policy_id="approval_token_invalid",
                    status="denied",
                )
            return ApprovalDecision(
                allowed=True,
                policy_id="approval_granted",
                status="approved",
            )
        if approval_status == "denied":
            return ApprovalDecision(
                allowed=False,
                policy_id="approval_denied",
                status="denied",
            )
        return ApprovalDecision(
            allowed=False,
            policy_id="approval_required",
            status="required",
        )

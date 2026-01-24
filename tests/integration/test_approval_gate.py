import json
from pathlib import Path

from skillos.approval_gate import ApprovalGate
from skillos.policy_engine import PolicyEngine, default_policy_path
from skillos.tool_wrapper import ToolWrapper


def test_approval_gate_blocks_high_risk_without_approval() -> None:
    wrapper = ToolWrapper()

    decision = wrapper.authorize("admin/delete_records", "delete all records")

    assert decision.requirement.required is True
    assert decision.approval.allowed is False
    assert decision.approval.policy_id == "approval_required"


def test_skill_policy_requires_approval_and_denial_blocks(tmp_path: Path) -> None:
    policy_path = default_policy_path(tmp_path)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        json.dumps(
            {
                "policies": [
                    {
                        "skill_id": "finance/close_books",
                        "requires_approval": True,
                        "policy_id": "close_books_policy",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    policy_engine = PolicyEngine.from_path(policy_path)
    wrapper = ToolWrapper(
        policy_engine=policy_engine,
        approval_gate=ApprovalGate(),
    )

    decision = wrapper.authorize(
        "finance/close_books",
        "generate summary",
        approval_status="denied",
    )

    assert decision.requirement.required is True
    assert decision.requirement.policy_id == "close_books_policy"
    assert decision.approval.allowed is False
    assert decision.approval.policy_id == "approval_denied"

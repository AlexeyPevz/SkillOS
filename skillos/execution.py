from __future__ import annotations

from dataclasses import dataclass

from skillos.execution_planner import ExecutionPlan
from skillos.preview_renderer import ExecutionPreview, render_preview
from skillos.skills.registry import SkillRegistry


@dataclass(frozen=True)
class ExecutionResult:
    plan: ExecutionPlan
    output: str | None
    preview: ExecutionPreview | None
    executed: bool


def execute_plan(
    registry: SkillRegistry,
    plan: ExecutionPlan,
    *,
    dry_run: bool,
    role: str | None = None,
    attributes: dict[str, object] | None = None,
    approval_status: str | None = None,
    approval_token: str | None = None,
    session_context: dict[str, object] | None = None,
    charge_budget: bool = True,
) -> ExecutionResult:
    if registry.get(plan.internal_skill_id) is None:
        raise KeyError(f"Unknown skill: {plan.internal_skill_id}")

    if dry_run:
        preview = render_preview(plan)
        return ExecutionResult(
            plan=plan,
            output=None,
            preview=preview,
            executed=False,
        )

    output = registry.execute(
        plan.internal_skill_id,
        payload=plan.payload,
        role=role,
        attributes=attributes,
        approval_status=approval_status,
        approval_token=approval_token,
        session_context=session_context,
        charge_budget=charge_budget,
    )
    return ExecutionResult(
        plan=plan,
        output=str(output),
        preview=None,
        executed=True,
    )

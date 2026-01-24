from __future__ import annotations

from dataclasses import dataclass

from skillos.execution_planner import ExecutionPlan


@dataclass(frozen=True)
class ExecutionPreview:
    plan_id: str
    affected_entities: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "affected_entities": self.affected_entities,
        }


def render_preview(plan: ExecutionPlan) -> ExecutionPreview:
    affected_entities = [plan.skill_id]
    return ExecutionPreview(plan_id=plan.plan_id, affected_entities=affected_entities)

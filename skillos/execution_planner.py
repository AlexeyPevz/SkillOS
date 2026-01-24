from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from skillos.storage import atomic_write_text

@dataclass(frozen=True)
class ExecutionPlan:
    skill_id: str
    internal_skill_id: str
    payload: str

    @property
    def plan_id(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, str]:
        return {
            "skill_id": self.skill_id,
            "internal_skill_id": self.internal_skill_id,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, str]) -> "ExecutionPlan":
        return cls(
            skill_id=payload["skill_id"],
            internal_skill_id=payload["internal_skill_id"],
            payload=payload["payload"],
        )


def build_execution_plan(
    skill_id: str, internal_skill_id: str, payload: str
) -> ExecutionPlan:
    return ExecutionPlan(
        skill_id=skill_id,
        internal_skill_id=internal_skill_id,
        payload=payload,
    )


def save_execution_plan(plan: ExecutionPlan, path: Path) -> None:
    path = Path(path)
    atomic_write_text(
        path,
        json.dumps(plan.to_dict(), ensure_ascii=True),
        encoding="utf-8",
    )


def load_execution_plan(path: Path) -> ExecutionPlan:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ExecutionPlan.from_dict(payload)

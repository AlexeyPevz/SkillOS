import json
from pathlib import Path

from skillos.authorization import default_permissions_path
from skillos.budget import default_budget_path
from skillos.orchestrator import Orchestrator
from skillos.skills.scaffold import scaffold_skill


def test_permission_denied_does_not_charge_budget(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    scaffold_skill("admin/list_users", root)

    permissions_path = default_permissions_path(root)
    permissions_path.parent.mkdir(parents=True, exist_ok=True)
    permissions_path.write_text(
        json.dumps(
            {
                "roles": {"viewer": []},
                "policies": [
                    {
                        "skill_id": "admin/list_users",
                        "required_permissions": ["admin:read"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    orchestrator = Orchestrator(root)
    result = orchestrator.run_query(
        "list users",
        execute=True,
        role="viewer",
    )

    assert result["status"] == "blocked"
    assert result["policy_id"] == "permission_denied"

    budget_path = default_budget_path(root)
    if budget_path.exists():
        payload = json.loads(budget_path.read_text(encoding="utf-8"))
        assert payload.get("daily", {}) == {}
        assert payload.get("monthly", {}) == {}

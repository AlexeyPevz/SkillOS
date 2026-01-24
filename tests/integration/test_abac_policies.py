import json
from pathlib import Path

from skillos.authorization import ABAC_DENIED_POLICY_ID, PermissionChecker, default_permissions_path


def test_abac_policy_denies_after_rbac_allows(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    permissions_path = default_permissions_path(root)
    permissions_path.parent.mkdir(parents=True, exist_ok=True)
    permissions_path.write_text(
        json.dumps(
            {
                "roles": {
                    "viewer": ["finance:write"],
                    "admin": ["finance:write"],
                },
                "policies": [
                    {
                        "skill_id": "finance/*",
                        "required_permissions": ["finance:write"],
                    }
                ],
                "abac_policies": [
                    {
                        "skill_id": "finance/*",
                        "effect": "deny",
                        "conditions": {"role": ["viewer"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    checker = PermissionChecker.from_path(permissions_path)

    allowed = checker.authorize("finance/close_books", "admin")
    assert allowed.allowed is True

    denied = checker.authorize("finance/close_books", "viewer")
    assert denied.allowed is False
    assert denied.policy_id == ABAC_DENIED_POLICY_ID

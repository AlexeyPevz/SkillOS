import json
from pathlib import Path

from skillos.authorization import (
    PERMISSION_DENIED_POLICY_ID,
    PERMISSION_GRANTED_POLICY_ID,
    PermissionChecker,
    default_permissions_path,
)


def test_rbac_role_mapping_enforces_permissions(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    permissions_path = default_permissions_path(root)
    permissions_path.parent.mkdir(parents=True, exist_ok=True)
    permissions_path.write_text(
        json.dumps(
            {
                "roles": {
                    "analyst": ["finance:read"],
                    "admin": ["finance:read", "finance:write"],
                },
                "policies": [
                    {
                        "skill_id": "finance/close_books",
                        "required_permissions": ["finance:write"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    checker = PermissionChecker.from_path(permissions_path)

    denied = checker.authorize("finance/close_books", "analyst")
    assert denied.allowed is False
    assert denied.policy_id == PERMISSION_DENIED_POLICY_ID

    allowed = checker.authorize("finance/close_books", "admin")
    assert allowed.allowed is True
    assert allowed.policy_id == PERMISSION_GRANTED_POLICY_ID

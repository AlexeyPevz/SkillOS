import json
from pathlib import Path

from click.testing import CliRunner

from skillos.authorization import default_permissions_path
from skillos.cli import cli
from skillos.telemetry import default_log_path


def test_permission_bypass_attempt_blocked_and_logged() -> None:
    runner = CliRunner()
    query = "list admin users"

    with runner.isolated_filesystem():
        root = Path("skills_root")
        add_result = runner.invoke(
            cli,
            ["add-skill", "admin/list_users", "--root", str(root)],
        )
        assert add_result.exit_code == 0

        permissions_path = default_permissions_path(root)
        permissions_path.parent.mkdir(parents=True, exist_ok=True)
        permissions_path.write_text(
            json.dumps(
                {
                    "roles": {"viewer": ["admin:read"]},
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

        result = runner.invoke(
            cli,
            [
                "run",
                query,
                "--root",
                str(root),
                "--execute",
                "--role",
                "admin",
            ],
        )

        assert result.exit_code == 0
        assert "permission_denied" in result.output

        log_path = default_log_path(root)
        assert log_path.exists()
        log_entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        permission = next(
            entry for entry in log_entries if entry["event"] == "permission_decision"
        )
        assert permission["allowed"] is False
        assert permission["policy_id"] == "permission_denied"

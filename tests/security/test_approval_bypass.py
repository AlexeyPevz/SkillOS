import json
from pathlib import Path

from click.testing import CliRunner

from skillos.cli import cli
from skillos.telemetry import default_log_path


def test_approval_bypass_attempt_is_blocked_and_logged() -> None:
    runner = CliRunner()
    query = "delete records for account"
    env = {"SKILLOS_APPROVAL_TOKEN": "secret"}

    with runner.isolated_filesystem():
        root = Path("skills_root")
        add_result = runner.invoke(
            cli,
            ["add-skill", "admin/delete_records", "--root", str(root)],
        )
        assert add_result.exit_code == 0

        result = runner.invoke(
            cli,
            [
                "run",
                query,
                "--root",
                str(root),
                "--execute",
                "--approval",
                "approved",
                "--approval-token",
                "wrong",
            ],
            env=env,
        )

        assert result.exit_code == 0
        assert "approval_token_invalid" in result.output

        log_path = default_log_path(root)
        assert log_path.exists()
        log_entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        policy = next(
            entry for entry in log_entries if entry["event"] == "policy_decision"
        )
        assert policy["allowed"] is False
        assert policy["policy_id"] == "approval_token_invalid"

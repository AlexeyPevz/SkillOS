from pathlib import Path

from click.testing import CliRunner

from skillos.cli import cli


def test_cli_blocks_risky_skill_until_approved() -> None:
    runner = CliRunner()
    query = "delete records for account"

    with runner.isolated_filesystem():
        root = Path("skills_root")
        add_result = runner.invoke(
            cli,
            ["add-skill", "admin/delete_records", "--root", str(root)],
        )
        assert add_result.exit_code == 0

        blocked = runner.invoke(
            cli,
            ["run", query, "--root", str(root), "--execute"],
        )
        assert blocked.exit_code == 0
        assert "approval_required" in blocked.output
        assert "executed" not in blocked.output

        approved = runner.invoke(
            cli,
            [
                "run",
                query,
                "--root",
                str(root),
                "--execute",
                "--approval",
                "approved",
            ],
        )
        assert approved.exit_code == 0
        assert "admin/delete_records executed" in approved.output

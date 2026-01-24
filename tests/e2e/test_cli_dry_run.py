from pathlib import Path

from click.testing import CliRunner

from skillos.cli import cli


def _extract_plan_id(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("plan_id:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("plan_id not found")


def test_cli_dry_run_then_approve_executes_same_plan() -> None:
    runner = CliRunner()
    query = "delete records for account"

    with runner.isolated_filesystem():
        root = Path("skills_root")
        add_result = runner.invoke(
            cli,
            ["add-skill", "admin/delete_records", "--root", str(root)],
        )
        assert add_result.exit_code == 0

        plan_path = Path("plan.json")
        preview = runner.invoke(
            cli,
            [
                "run",
                query,
                "--root",
                str(root),
                "--execute",
                "--dry-run",
                "--plan-path",
                str(plan_path),
            ],
        )
        assert preview.exit_code == 0
        assert plan_path.exists()
        assert "affected_entities" in preview.output
        preview_plan_id = _extract_plan_id(preview.output)

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
                "--plan-path",
                str(plan_path),
            ],
        )
        assert approved.exit_code == 0
        assert "admin/delete_records executed" in approved.output
        approved_plan_id = _extract_plan_id(approved.output)
        assert approved_plan_id == preview_plan_id

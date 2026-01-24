from click.testing import CliRunner

from skillos.budget import default_budget_path
from skillos.cli import cli


def test_dry_run_does_not_write_budget_usage(skill_root) -> None:
    runner = CliRunner()
    query = "Search flights from Moscow to Sochi on May 10."

    result = runner.invoke(
        cli,
        ["run", query, "--root", str(skill_root), "--execute", "--dry-run"],
    )

    assert result.exit_code == 0
    assert not default_budget_path(skill_root).exists()

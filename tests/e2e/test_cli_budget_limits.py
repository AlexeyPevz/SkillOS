from click.testing import CliRunner

from skillos.cli import cli


def test_cli_budget_exceeded_returns_message(skill_root) -> None:
    runner = CliRunner()
    query = "Search flights from Moscow to Sochi on May 10."
    implementation_dir = skill_root / "implementations" / "travel"
    implementation_dir.mkdir(parents=True, exist_ok=True)
    (implementation_dir / "search_flights.py").write_text(
        "def run(payload='ok'):\n    return payload\n",
        encoding="utf-8",
    )
    env = {
        "SKILLOS_BUDGET_PER_REQUEST": "5",
        "SKILLOS_BUDGET_DAILY": "1",
        "SKILLOS_BUDGET_MONTHLY": "10",
        "SKILLOS_BUDGET_LOW_REMAINING": "0",
        "SKILLOS_MODEL_STANDARD_COST": "0.6",
        "SKILLOS_MODEL_CHEAP_COST": "0.6",
    }

    first = runner.invoke(
        cli,
        ["run", query, "--root", str(skill_root), "--execute"],
        env=env,
    )
    assert first.exit_code == 0

    second = runner.invoke(
        cli,
        ["run", query, "--root", str(skill_root), "--execute"],
        env=env,
    )
    assert second.exit_code == 0
    assert "budget_exceeded" in second.output
    assert "daily_limit" in second.output

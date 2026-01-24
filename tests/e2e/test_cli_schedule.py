from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from click.testing import CliRunner

from skillos.cli import cli
from skillos.telemetry import default_log_path


def test_cli_schedule_add_and_tick_executes_due() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        root = Path("skills_root")
        add_skill = runner.invoke(
            cli,
            ["add-skill", "ops/daily_report", "--root", str(root)],
        )
        assert add_skill.exit_code == 0

        run_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        add_schedule = runner.invoke(
            cli,
            [
                "schedule",
                "add",
                "ops/daily_report",
                "--root",
                str(root),
                "--run-at",
                run_at,
            ],
        )
        assert add_schedule.exit_code == 0
        assert "schedule_added" in add_schedule.output

        tick = runner.invoke(
            cli,
            ["schedule", "tick", "--root", str(root)],
        )
        assert tick.exit_code == 0
        assert "schedule_completed" in tick.output

        log_path = default_log_path(root)
        assert log_path.exists()
        entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        assert any(entry["event"] == "schedule_completed" for entry in entries)

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from click.testing import CliRunner

from skillos.cli import cli
from skillos.schedules import ScheduleStore, build_schedule, default_schedules_path
from skillos.skills.scaffold import scaffold_skill
from skillos.telemetry import default_log_path


def test_schedule_tick_emits_pipeline_events() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        root = Path("skills_root")
        scaffold_skill("ops/sample", root)
        run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        store = ScheduleStore(default_schedules_path(root))
        store.save([build_schedule("ops/sample", run_at)])

        result = runner.invoke(
            cli,
            ["schedule", "tick", "--root", str(root)],
        )
        assert result.exit_code == 0

        log_path = default_log_path(root)
        assert log_path.exists()
        entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        events = {entry["event"] for entry in entries}
        assert "schedule_due" in events
        assert "schedule_started" in events
        assert "schedule_completed" in events
        assert "budget_check" in events
        assert "permission_decision" in events
        assert "policy_decision" in events
        assert "execution_result" in events

        execution = next(
            entry for entry in entries if entry["event"] == "execution_result"
        )
        assert execution["status"] == "success"

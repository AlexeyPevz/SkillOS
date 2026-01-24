import json
from pathlib import Path

from click.testing import CliRunner

from skillos.cli import cli
from skillos.telemetry import default_log_path


def test_cli_job_enqueue_and_work_logs_events() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        root = Path("skills_root")
        add_skill = runner.invoke(
            cli,
            ["add-skill", "ops/sample", "--root", str(root)],
        )
        assert add_skill.exit_code == 0

        enqueue = runner.invoke(
            cli,
            ["job", "enqueue", "ops/sample", "--root", str(root)],
        )
        assert enqueue.exit_code == 0
        assert "job_enqueued" in enqueue.output

        work = runner.invoke(
            cli,
            ["job", "work", "--root", str(root)],
        )
        assert work.exit_code == 0
        assert "job_succeeded" in work.output

        log_path = default_log_path(root)
        assert log_path.exists()
        entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        events = {entry["event"] for entry in entries}
        assert "job_enqueued" in events
        assert "job_started" in events
        assert "job_succeeded" in events

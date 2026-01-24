import json

from click.testing import CliRunner

from skillos.cli import cli
from skillos.telemetry import default_log_path


def test_cli_run_logs_selection(skill_root):
    runner = CliRunner()
    query = "Search flights from Moscow to Sochi on May 10."

    result = runner.invoke(
        cli,
        ["run", query, "--root", str(skill_root)],
    )

    assert result.exit_code == 0
    log_path = default_log_path(skill_root)
    assert log_path.exists()
    log_entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    events = {entry["event"] for entry in log_entries}
    assert "request_received" in events
    assert "routing_decision" in events
    decision = next(entry for entry in log_entries if entry["event"] == "routing_decision")
    assert decision["skill_id"] == "travel.search_flights"
    assert all("request_id" in entry for entry in log_entries)

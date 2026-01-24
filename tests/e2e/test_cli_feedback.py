import json

from click.testing import CliRunner

from skillos.cli import cli
from skillos.telemetry import default_log_path


def _latest_routing_decision(log_path):
    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    decisions = [entry for entry in entries if entry["event"] == "routing_decision"]
    return decisions[-1]


def test_cli_feedback_correction_improves_routing(skill_root):
    runner = CliRunner()
    query = "Search travel itinerary options"

    result = runner.invoke(cli, ["run", query, "--root", str(skill_root)])
    assert result.exit_code == 0

    log_path = default_log_path(skill_root)
    decision_before = _latest_routing_decision(log_path)
    assert decision_before["skill_id"] == "travel.search_flights"

    feedback = runner.invoke(
        cli,
        [
            "feedback",
            decision_before["skill_id"],
            "--expected-skill-id",
            "travel.build_itinerary",
            "--root",
            str(skill_root),
        ],
    )
    assert feedback.exit_code == 0

    result = runner.invoke(cli, ["run", query, "--root", str(skill_root)])
    assert result.exit_code == 0

    decision_after = _latest_routing_decision(log_path)
    assert decision_after["skill_id"] == "travel.build_itinerary"

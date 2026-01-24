import json
from pathlib import Path

from skillos.routing import SkillRouter
from skillos.skills.registry import SkillRegistry
from skillos.telemetry import EventLogger, route_with_telemetry


def test_routing_logs_candidates_and_decision(skill_root, tmp_path):
    registry = SkillRegistry(skill_root)
    records = registry.load_all()
    router = SkillRouter([record.metadata for record in records.values()])

    golden_queries = json.loads(
        Path("tests/fixtures/golden_queries.json").read_text(encoding="utf-8")
    )
    query = golden_queries[0]["query"]

    log_path = tmp_path / "routing.log"
    logger = EventLogger(log_path, request_id="req-logging")
    route_with_telemetry(query, router, logger, "req-logging")

    log_entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    candidates = next(
        entry for entry in log_entries if entry["event"] == "routing_candidates"
    )
    assert candidates["candidates"]
    assert "score" in candidates["candidates"][0]
    decision = next(entry for entry in log_entries if entry["event"] == "routing_decision")
    assert decision["confidence"] >= 0
    assert decision["reason"]

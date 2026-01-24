import json

import pytest

from skillos.telemetry import EventLogger, LogSchemaError, hash_query


def test_log_schema_requires_fields(tmp_path):
    log_path = tmp_path / "events.log"
    logger = EventLogger(log_path, request_id="req-001")

    with pytest.raises(LogSchemaError):
        logger.log("request_received", query_length=3, token_count=1)

    logger.log(
        "request_received",
        query_hash=hash_query("ok"),
        query_length=2,
        token_count=1,
    )


def test_log_redacts_pii(tmp_path):
    log_path = tmp_path / "events.log"
    logger = EventLogger(log_path, request_id="req-002")

    logger.log(
        "request_received",
        query_hash=hash_query("reach out"),
        query_length=11,
        token_count=2,
        query="Contact me at test@example.com",
    )

    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert "test@example.com" not in entry["query"]
    assert "[REDACTED]" in entry["query"]

import base64
import json
from pathlib import Path
import time

from skillos.jobs import JobStore, default_jobs_db_path
from skillos.skills.scaffold import scaffold_skill
from skillos.telemetry import default_log_path
from skillos.webhooks import (
    build_signature_header,
    default_webhook_path,
    handle_webhook_event,
)


def test_webhook_ingests_attachments(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "skills_root"
    scaffold_skill("ops/sample", root)
    monkeypatch.setenv("SKILLOS_WEBHOOK_SECRET", "secret")

    trigger_path = default_webhook_path(root)
    trigger_path.parent.mkdir(parents=True, exist_ok=True)
    trigger_path.write_text(
        json.dumps(
            {"webhooks": [{"id": "sample-hook", "skill_id": "ops/sample"}]},
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    attachment_bytes = b"payload"
    payload_path = root / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "payload": {"message": "hello"},
                "attachments": [
                    {
                        "filename": "note.txt",
                        "content_type": "text/plain",
                        "data": base64.b64encode(attachment_bytes).decode("ascii"),
                    }
                ],
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    raw_payload = payload_path.read_text(encoding="utf-8")
    signature = build_signature_header(
        "secret",
        raw_payload,
        timestamp=int(time.time()),
    )
    result = handle_webhook_event(
        "sample-hook",
        payload_path,
        root,
        signature=signature,
    )

    assert result.status == "enqueued"

    store = JobStore(default_jobs_db_path(root))
    jobs = store.list_all()
    assert len(jobs) == 1
    job_payload = json.loads(jobs[0].payload)
    assert job_payload["payload"] == {"message": "hello"}
    attachments = job_payload["attachments"]
    assert len(attachments) == 1
    attachment = attachments[0]
    assert attachment["filename"] == "note.txt"
    assert attachment["content_type"] == "text/plain"
    assert attachment["size_bytes"] == len(attachment_bytes)

    stored = root / attachment["reference"]
    assert stored.exists()
    assert stored.read_bytes() == attachment_bytes

    log_path = default_log_path(root)
    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    ingest_events = [
        entry for entry in entries if entry.get("event") == "attachments_ingested"
    ]
    assert ingest_events
    event = ingest_events[0]
    assert event["count"] == 1
    assert event["attachments"][0]["content_type"] == "text/plain"
    assert event["attachments"][0]["size_bytes"] == len(attachment_bytes)
    assert "data" not in event["attachments"][0]

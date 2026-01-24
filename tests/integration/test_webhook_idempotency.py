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


def test_webhook_idempotency_skips_duplicates(
    tmp_path: Path, monkeypatch
) -> None:
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

    payload_path = root / "payload.json"
    payload_path.write_text(
        json.dumps(
            {"payload": "ok", "idempotency_key": "evt-1"},
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
    first = handle_webhook_event(
        "sample-hook",
        payload_path,
        root,
        signature=signature,
    )
    second = handle_webhook_event(
        "sample-hook",
        payload_path,
        root,
        signature=signature,
    )

    assert first.status == "enqueued"
    assert second.status == "skipped"

    store = JobStore(default_jobs_db_path(root))
    jobs = store.list_all()
    assert len(jobs) == 1

    log_path = default_log_path(root)
    assert log_path.exists()
    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert any(entry["event"] == "idempotency_skipped" for entry in entries)

import json
from pathlib import Path
import time

from click.testing import CliRunner

from skillos.cli import cli
from skillos.telemetry import default_log_path
from skillos.webhooks import build_signature_header, default_webhook_path


def test_cli_webhook_handle_deduplicates_events() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        root = Path("skills_root")
        add_skill = runner.invoke(
            cli,
            ["add-skill", "ops/sample", "--root", str(root)],
        )
        assert add_skill.exit_code == 0

        trigger_path = default_webhook_path(root)
        trigger_path.parent.mkdir(parents=True, exist_ok=True)
        trigger_path.write_text(
            json.dumps(
                {"webhooks": [{"id": "sample-hook", "skill_id": "ops/sample"}]},
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )

        payload_path = Path("payload.json")
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

        first = runner.invoke(
            cli,
            [
                "webhook",
                "handle",
                "--id",
                "sample-hook",
                "--path",
                str(payload_path),
                "--root",
                str(root),
                "--signature",
                signature,
            ],
            env={"SKILLOS_WEBHOOK_SECRET": "secret"},
        )
        assert first.exit_code == 0
        assert "webhook_enqueued" in first.output

        second = runner.invoke(
            cli,
            [
                "webhook",
                "handle",
                "--id",
                "sample-hook",
                "--path",
                str(payload_path),
                "--root",
                str(root),
                "--signature",
                signature,
            ],
            env={"SKILLOS_WEBHOOK_SECRET": "secret"},
        )
        assert second.exit_code == 0
        assert "webhook_skipped" in second.output

        work = runner.invoke(
            cli,
            ["job", "work", "--root", str(root)],
        )
        assert work.exit_code == 0
        assert "job_succeeded" in work.output

        log_path = default_log_path(root)
        entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        enqueued = [entry for entry in entries if entry["event"] == "job_enqueued"]
        assert len(enqueued) == 1
        executed = [
            entry
            for entry in entries
            if entry["event"] == "execution_result" and entry["status"] == "success"
        ]
        assert len(executed) == 1
        assert any(entry["event"] == "idempotency_skipped" for entry in entries)

import json
from pathlib import Path

import pytest

from skillos.skills.scaffold import scaffold_skill
from skillos.webhooks import (
    WebhookSignatureError,
    default_webhook_path,
    handle_webhook_event,
)


def _write_trigger(root: Path) -> None:
    trigger_path = default_webhook_path(root)
    trigger_path.parent.mkdir(parents=True, exist_ok=True)
    trigger_path.write_text(
        json.dumps(
            {"webhooks": [{"id": "sample-hook", "skill_id": "ops/sample"}]},
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )


def _write_payload(root: Path) -> Path:
    payload_path = root / "payload.json"
    payload_path.write_text(
        json.dumps({"payload": "ok"}, ensure_ascii=True),
        encoding="utf-8",
    )
    return payload_path


def test_webhook_requires_signature_when_secret_missing(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "skills_root"
    scaffold_skill("ops/sample", root)
    _write_trigger(root)
    payload_path = _write_payload(root)

    monkeypatch.delenv("SKILLOS_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("SKILLOS_WEBHOOK_ALLOW_UNSIGNED", raising=False)

    with pytest.raises(WebhookSignatureError) as exc:
        handle_webhook_event("sample-hook", payload_path, root)
    assert exc.value.status_code == 401


def test_webhook_allows_unsigned_when_flag_set(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "skills_root"
    scaffold_skill("ops/sample", root)
    _write_trigger(root)
    payload_path = _write_payload(root)

    monkeypatch.delenv("SKILLOS_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("SKILLOS_WEBHOOK_ALLOW_UNSIGNED", "1")

    result = handle_webhook_event("sample-hook", payload_path, root)
    assert result.status == "enqueued"

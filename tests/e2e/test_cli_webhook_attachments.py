import base64
import json
from pathlib import Path
import time

from click.testing import CliRunner
import yaml

from skillos.cli import cli
from skillos.webhooks import build_signature_header, default_webhook_path


def _write_capture_skill(root: Path, skill_id: str) -> Path:
    domain, name = skill_id.split("/", 1)
    metadata_dir = root / "metadata" / domain
    implementation_dir = root / "implementations" / domain
    metadata_dir.mkdir(parents=True, exist_ok=True)
    implementation_dir.mkdir(parents=True, exist_ok=True)

    for package_dir in [root / "implementations", implementation_dir]:
        init_file = package_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")

    metadata = {
        "id": skill_id,
        "name": "Capture Payload",
        "description": "Captures webhook payload",
        "version": "0.1.0",
        "entrypoint": f"implementations.{domain}.{name}:run",
        "tags": [domain],
    }
    metadata_file = metadata_dir / f"{name}.yaml"
    metadata_file.write_text(
        yaml.safe_dump(metadata, sort_keys=False),
        encoding="utf-8",
    )

    implementation_file = implementation_dir / f"{name}.py"
    output_path = implementation_dir / "payload.json"
    implementation_file.write_text(
        "from pathlib import Path\n\n"
        "def run(payload: str = 'ok') -> str:\n"
        "    output_path = Path(__file__).with_name('payload.json')\n"
        "    output_path.write_text(payload, encoding='utf-8')\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )
    return output_path


def test_cli_webhook_handles_attachments() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        root = Path("skills_root")
        output_path = _write_capture_skill(root, "ops/capture")

        trigger_path = default_webhook_path(root)
        trigger_path.parent.mkdir(parents=True, exist_ok=True)
        trigger_path.write_text(
            json.dumps(
                {"webhooks": [{"id": "capture-hook", "skill_id": "ops/capture"}]},
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )

        attachment_data = base64.b64encode(b"image-data").decode("ascii")
        payload_path = Path("payload.json")
        payload_path.write_text(
            json.dumps(
                {
                    "payload": "hello",
                    "attachments": [
                        {
                            "filename": "image.png",
                            "content_type": "image/png",
                            "data": attachment_data,
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

        enqueue = runner.invoke(
            cli,
            [
                "webhook",
                "handle",
                "--id",
                "capture-hook",
                "--path",
                str(payload_path),
                "--root",
                str(root),
                "--signature",
                signature,
            ],
            env={"SKILLOS_WEBHOOK_SECRET": "secret"},
        )
        assert enqueue.exit_code == 0
        assert "webhook_enqueued" in enqueue.output

        work = runner.invoke(cli, ["job", "work", "--root", str(root)])
        assert work.exit_code == 0
        assert "job_succeeded" in work.output

        captured_payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert captured_payload["payload"] == "hello"
        attachments = captured_payload["attachments"]
        assert len(attachments) == 1
        attachment = attachments[0]
        assert attachment["content_type"] == "image/png"
        assert Path(attachment["reference"]).parts[0] == "attachments"

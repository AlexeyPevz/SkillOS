import json
from pathlib import Path

import httpx
import yaml

from skillos.connectors import ConnectorRegistry, default_secrets_path
from skillos.telemetry import EventLogger
from skillos.testing import mock_external_apis


def _write_connector(root: Path, payload: dict[str, object]) -> None:
    connectors_path = root / "connectors"
    connectors_path.mkdir(parents=True, exist_ok=True)
    connector_file = connectors_path / "weather.yaml"
    connector_file.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def test_secret_resolution_and_logging_redaction(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_connector(
        root,
        {
            "id": "weather",
            "type": "http",
            "base_url": "https://api.example.com",
            "auth": {"type": "bearer", "token": "secret:API_TOKEN"},
        },
    )
    secrets_path = default_secrets_path(root)
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text(
        "SKILLOS_WEATHER_API_TOKEN=token-123\n",
        encoding="utf-8",
    )

    log_path = tmp_path / "events.log"
    logger = EventLogger(log_path, request_id="req-secret")
    registry = ConnectorRegistry(root, logger=logger, secrets_path=secrets_path)
    registry.load_all()
    connector = registry.get("weather")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token-123"
        return httpx.Response(200, json={"ok": True})

    with mock_external_apis(handler=handler):
        connector.request("GET", "/ping")

    secret_value = registry.resolver.resolve("API_TOKEN", integration="weather")
    logger.log(
        "integration_call",
        connector_id="weather",
        connector_type="http",
        status="success",
        latency_ms=0.0,
        token=secret_value,
    )

    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    redacted = next(entry for entry in entries if "token" in entry)
    assert redacted["token"] == "[REDACTED]"
    assert "token-123" not in log_path.read_text(encoding="utf-8")

import json
from pathlib import Path

import httpx
import yaml

from skillos.connectors import ConnectorRegistry
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


def test_http_connector_logs_integration_call(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "skills"
    _write_connector(
        root,
        {
            "id": "weather",
            "type": "http",
            "base_url": "https://api.example.com",
            "headers": {"X-Client": "skillos"},
            "auth": {"type": "bearer", "token": "secret:API_TOKEN"},
        },
    )
    monkeypatch.setenv("API_TOKEN", "token-123")

    log_path = tmp_path / "events.log"
    logger = EventLogger(log_path, request_id="req-connector")
    registry = ConnectorRegistry(root, logger=logger)
    registry.load_all()
    connector = registry.get("weather")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token-123"
        assert request.headers["X-Client"] == "skillos"
        return httpx.Response(200, json={"ok": True})

    with mock_external_apis(handler=handler):
        response = connector.request("GET", "/ping")

    assert response.status_code == 200
    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    integration = next(
        entry for entry in entries if entry["event"] == "integration_call"
    )
    assert integration["connector_id"] == "weather"
    assert integration["connector_type"] == "http"
    assert integration["status"] == "success"
    assert integration["status_code"] == 200
    assert integration["method"] == "GET"
    assert integration["latency_ms"] >= 0

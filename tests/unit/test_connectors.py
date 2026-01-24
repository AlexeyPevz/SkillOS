from pathlib import Path

import pytest
import yaml

from skillos.connectors import (
    ConnectorRegistry,
    ConnectorSchemaError,
    SecretValue,
)


def _write_connector(root: Path, payload: dict[str, object]) -> Path:
    connectors_path = root / "connectors"
    connectors_path.mkdir(parents=True, exist_ok=True)
    connector_file = connectors_path / "sample.yaml"
    connector_file.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    return connector_file


def test_connector_schema_validation_errors(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_connector(root, {"id": "demo", "type": "http"})

    registry = ConnectorRegistry(root)
    with pytest.raises(ConnectorSchemaError) as exc:
        registry.load_all()

    assert "base_url" in str(exc.value)


def test_secret_resolution_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setenv("API_TOKEN", "super-secret")

    registry = ConnectorRegistry(root)
    registry.load_all()

    connector = registry.get("weather")
    assert "API_TOKEN" in registry.required_secrets("weather")
    assert connector.auth is not None
    assert isinstance(connector.auth.token, SecretValue)
    assert connector.auth.token.value == "super-secret"
    assert str(connector.auth.token) == "[REDACTED]"

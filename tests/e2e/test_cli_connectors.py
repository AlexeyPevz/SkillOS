from pathlib import Path
import json

import httpx
from click.testing import CliRunner
import yaml

from skillos.cli import cli
from skillos.testing import mock_external_apis


def _write_skill(root: Path) -> None:
    metadata_dir = root / "metadata" / "integration"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    implementation_dir = root / "implementations" / "integration"
    implementation_dir.mkdir(parents=True, exist_ok=True)
    (root / "implementations" / "__init__.py").write_text("", encoding="utf-8")
    (implementation_dir / "__init__.py").write_text("", encoding="utf-8")

    metadata = {
        "id": "integration/use_connector",
        "name": "Use Connector",
        "description": "Execute a connector-backed request.",
        "version": "0.1.0",
        "entrypoint": "implementations.integration.use_connector:run",
        "tags": ["integration"],
    }
    (metadata_dir / "use_connector.yaml").write_text(
        yaml.safe_dump(metadata, sort_keys=False),
        encoding="utf-8",
    )

    implementation = (
        "from skillos.connectors import ConnectorRegistry, resolve_skills_root\n\n"
        "def run(payload: str = 'ok') -> str:\n"
        "    registry = ConnectorRegistry(resolve_skills_root())\n"
        "    registry.load_all()\n"
        "    connector = registry.get('weather_api')\n"
        "    response = connector.request('GET', '/ping')\n"
        "    return f'connector_status={response.status_code}'\n"
    )
    (implementation_dir / "use_connector.py").write_text(
        implementation, encoding="utf-8"
    )


def test_cli_add_connector_and_run_skill() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        root = Path("skills_root")

        result = runner.invoke(
            cli,
            ["add-connector", "weather_api", "--root", str(root), "--type", "http"],
        )
        assert result.exit_code == 0

        connector_file = root / "connectors" / "weather_api.yaml"
        assert connector_file.exists()
        payload = yaml.safe_load(connector_file.read_text(encoding="utf-8"))
        payload["base_url"] = "https://api.example.com"
        payload["headers"] = {"X-Client": "skillos"}
        payload["auth"] = {"type": "bearer", "token": "secret:API_TOKEN"}
        payload["timeout_seconds"] = 5
        payload["rate_limit_per_minute"] = 60
        connector_file.write_text(
            yaml.safe_dump(payload, sort_keys=False),
            encoding="utf-8",
        )

        _write_skill(root)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer token-abc"
            return httpx.Response(200, json={"ok": True})

        with mock_external_apis(handler=handler):
            run_result = runner.invoke(
                cli,
                ["run-skill", "integration/use_connector", "--root", str(root)],
                env={"API_TOKEN": "token-abc"},
            )
        assert run_result.exit_code == 0
        assert "connector_status=200" in run_result.output

        log_path = root / "logs" / "execution.log"
        entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        assert any(entry["event"] == "integration_call" for entry in entries)

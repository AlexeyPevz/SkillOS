from pathlib import Path

from click.testing import CliRunner
import yaml

from skillos.cli import cli
from skillos.connectors import default_secrets_path


def _write_connector(root: Path, payload: dict[str, object]) -> None:
    connectors_path = root / "connectors"
    connectors_path.mkdir(parents=True, exist_ok=True)
    connector_file = connectors_path / "weather.yaml"
    connector_file.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def test_cli_secrets_init_writes_env_and_hides_values() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        root = Path("skills_root")
        _write_connector(
            root,
            {
                "id": "weather",
                "type": "http",
                "base_url": "https://api.example.com",
                "auth": {"type": "bearer", "token": "secret:API_TOKEN"},
            },
        )
        Path(".env.example").write_text("SKILLOS_ENV=dev\n", encoding="utf-8")

        result = runner.invoke(
            cli,
            [
                "secrets",
                "init",
                "--connector",
                "weather",
                "--root",
                str(root),
            ],
            input="token-xyz\n",
        )

        assert result.exit_code == 0
        assert "required_secrets" in result.output
        assert "API_TOKEN" in result.output
        assert "token-xyz" not in result.output

        secrets_file = default_secrets_path(root)
        assert secrets_file.exists()
        assert (
            "SKILLOS_WEATHER_API_TOKEN=token-xyz"
            in secrets_file.read_text(encoding="utf-8")
        )
        assert (
            "SKILLOS_WEATHER_API_TOKEN=changeme"
            in Path(".env.example").read_text(encoding="utf-8")
        )

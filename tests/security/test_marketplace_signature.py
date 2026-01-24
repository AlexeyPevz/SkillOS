import json
from pathlib import Path

from click.testing import CliRunner

from skillos.cli import cli
from skillos.telemetry import default_log_path


def _catalog_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "marketplace"
        / "catalog_tampered.json"
    )


def test_tampered_package_rejected_and_logged() -> None:
    runner = CliRunner()
    catalog_path = _catalog_path()

    with runner.isolated_filesystem():
        root = Path("skills_root")
        result = runner.invoke(
            cli,
            [
                "marketplace",
                "install",
                "community/base",
                "--root",
                str(root),
                "--catalog",
                str(catalog_path),
            ],
        )
        assert result.exit_code != 0
        assert "signature_verification_failed" in result.output

        log_path = default_log_path(root)
        assert log_path.exists()
        entries = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        event = next(
            entry
            for entry in entries
            if entry["event"] == "marketplace_install_rejected"
        )
        assert event["package_id"] == "community/base"
        assert event["reason"] == "invalid_signature"

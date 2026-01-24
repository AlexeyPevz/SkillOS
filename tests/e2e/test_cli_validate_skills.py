from pathlib import Path

import yaml
from click.testing import CliRunner

from skillos.cli import cli


def _write_metadata(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def test_cli_validate_reports_invalid_entrypoint() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        root = Path("skills_root")
        metadata_file = root / "metadata" / "travel" / "missing.yaml"
        _write_metadata(
            metadata_file,
            {
                "id": "travel/missing",
                "name": "Missing",
                "description": "Missing implementation",
                "version": "1.0.0",
                "entrypoint": "implementations.travel.missing:run",
                "tags": ["travel"],
            },
        )

        result = runner.invoke(
            cli, ["validate", "--root", str(root)]
        )
        assert result.exit_code != 0
        assert "invalid_skill" in result.output

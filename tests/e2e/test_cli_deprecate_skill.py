from pathlib import Path

import yaml
from click.testing import CliRunner

from skillos.cli import cli


def test_cli_deprecate_and_undeprecate_skill() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        root = Path("skills_root")
        result = runner.invoke(
            cli,
            ["add-skill", "travel/search_flights", "--root", str(root)],
        )
        assert result.exit_code == 0

        result = runner.invoke(
            cli,
            [
                "deprecate-skill",
                "travel/search_flights",
                "--root",
                str(root),
                "--reason",
                "use travel/search_hotels",
                "--replacement",
                "travel/search_hotels",
            ],
        )
        assert result.exit_code == 0

        metadata_file = root / "metadata" / "travel" / "search_flights.yaml"
        payload = yaml.safe_load(metadata_file.read_text(encoding="utf-8"))
        assert payload["deprecated"] is True
        assert payload["deprecation_reason"] == "use travel/search_hotels"
        assert payload["replacement_id"] == "travel/search_hotels"

        result = runner.invoke(
            cli,
            [
                "undeprecate-skill",
                "travel/search_flights",
                "--root",
                str(root),
            ],
        )
        assert result.exit_code == 0

        payload = yaml.safe_load(metadata_file.read_text(encoding="utf-8"))
        assert payload.get("deprecated") is False
        assert "deprecation_reason" not in payload
        assert "replacement_id" not in payload

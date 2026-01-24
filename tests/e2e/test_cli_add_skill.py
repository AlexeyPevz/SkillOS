from pathlib import Path

import yaml
from click.testing import CliRunner

from skillos.cli import cli


def test_cli_add_skill_and_run():
    runner = CliRunner()
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "skills"
        / "valid_skill_runtime.yaml"
    )

    with runner.isolated_filesystem():
        root = Path("skills_root")
        result = runner.invoke(
            cli,
            ["add-skill", "travel/search_flights", "--root", str(root)],
        )
        assert result.exit_code == 0

        metadata_file = root / "metadata" / "travel" / "search_flights.yaml"
        implementation_file = root / "implementations" / "travel" / "search_flights.py"
        assert metadata_file.exists()
        assert implementation_file.exists()

        assert yaml.safe_load(
            metadata_file.read_text(encoding="utf-8")
        ) == yaml.safe_load(fixture_path.read_text(encoding="utf-8"))

        run_result = runner.invoke(
            cli,
            ["run-skill", "travel/search_flights", "--root", str(root)],
        )
        assert run_result.exit_code == 0
        assert "travel/search_flights executed" in run_result.output

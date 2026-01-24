from pathlib import Path

from click.testing import CliRunner

from skillos.cli import cli
from skillos.testing import default_coverage_path


def test_cli_test_generates_coverage() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        root = Path("skills_root")
        add_result = runner.invoke(
            cli,
            ["add-skill", "travel/search_flights", "--root", str(root)],
        )
        assert add_result.exit_code == 0

        test_result = runner.invoke(
            cli,
            ["test", "travel/search_flights", "--root", str(root)],
        )
        assert test_result.exit_code == 0
        coverage_path = default_coverage_path(root, "travel/search_flights")
        assert coverage_path.exists()
        assert f"coverage_written: {coverage_path}" in test_result.output

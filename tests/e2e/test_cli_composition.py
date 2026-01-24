from pathlib import Path

from click.testing import CliRunner

from skillos.cli import cli


def test_cli_composed_skill_requires_tests_before_activation() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        root = Path("skills")
        result = runner.invoke(
            cli,
            ["add-skill", "travel/search_flights", "--root", str(root)],
        )
        assert result.exit_code == 0
        result = runner.invoke(
            cli,
            ["add-skill", "travel/build_itinerary", "--root", str(root)],
        )
        assert result.exit_code == 0

        compose_result = runner.invoke(
            cli,
            [
                "compose-skill",
                "travel/plan_trip",
                "--root",
                str(root),
                "--step",
                "travel/search_flights",
                "--step",
                "travel/build_itinerary",
            ],
        )
        assert compose_result.exit_code == 0

        activation_missing = runner.invoke(
            cli,
            [
                "activate-skill",
                "travel/plan_trip",
                "--root",
                str(root),
                "--approval",
                "approved",
            ],
        )
        assert activation_missing.exit_code != 0
        assert "tests_required" in activation_missing.output

        test_result = runner.invoke(
            cli,
            ["test", "travel/plan_trip", "--root", str(root)],
        )
        assert test_result.exit_code == 0

        activation_required = runner.invoke(
            cli,
            ["activate-skill", "travel/plan_trip", "--root", str(root)],
        )
        assert activation_required.exit_code != 0
        assert "approval_required" in activation_required.output

        activation_success = runner.invoke(
            cli,
            [
                "activate-skill",
                "travel/plan_trip",
                "--root",
                str(root),
                "--approval",
                "approved",
            ],
        )
        assert activation_success.exit_code == 0
        assert "activation_success" in activation_success.output

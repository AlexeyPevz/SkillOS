from pathlib import Path

from click.testing import CliRunner

from skillos.cli import cli


def test_cli_parallel_composed_skill_outputs_all_branches() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        root = Path("skills")
        result = runner.invoke(
            cli,
            ["add-skill", "travel/alpha", "--root", str(root)],
        )
        assert result.exit_code == 0
        result = runner.invoke(
            cli,
            ["add-skill", "travel/beta", "--root", str(root)],
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
                "travel/alpha|travel/beta",
            ],
        )
        assert compose_result.exit_code == 0

        test_result = runner.invoke(cli, ["test", "travel/plan_trip", "--root", str(root)])
        assert test_result.exit_code == 0

        activation_result = runner.invoke(
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
        assert activation_result.exit_code == 0

        run_result = runner.invoke(
            cli,
            [
                "run-skill",
                "travel/plan_trip",
                "--root",
                str(root),
                "--payload",
                "start",
            ],
        )
        assert run_result.exit_code == 0
        assert "travel/alpha executed" in run_result.output
        assert "travel/beta executed" in run_result.output
        assert run_result.output.index("travel/alpha executed") < run_result.output.index(
            "travel/beta executed"
        )

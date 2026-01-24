from click.testing import CliRunner

from skillos.cli import cli


def test_cli_trace_renders_timings(skill_root) -> None:
    runner = CliRunner()
    query = "Search flights to Sochi"

    result = runner.invoke(
        cli,
        [
            "run",
            query,
            "--root",
            str(skill_root),
            "--debug",
            "--profile",
            "--trace",
        ],
    )

    assert result.exit_code == 0
    assert "trace:" in result.output
    assert "route" in result.output
    assert "inputs:" in result.output
    assert "outputs:" in result.output
    assert "ms" in result.output

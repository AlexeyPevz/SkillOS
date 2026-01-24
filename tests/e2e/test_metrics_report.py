import json

from click.testing import CliRunner

from skillos.cli import cli


def test_metrics_report_created(skill_root, tmp_path):
    runner = CliRunner()
    output_path = tmp_path / "metrics.json"

    result = runner.invoke(
        cli,
        [
            "metrics",
            "--root",
            str(skill_root),
            "--golden",
            "tests/fixtures/golden_queries.json",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["metrics"]

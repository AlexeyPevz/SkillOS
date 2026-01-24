import json

from click.testing import CliRunner

from skillos.cli import cli
from skillos.optimizer import default_optimization_log_path


def test_cli_optimizer_logs_decision(skill_root) -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "optimize",
            "zakupki/search_tenders",
            "--variant",
            "v1",
            "--variant",
            "v2",
            "--baseline",
            "v1",
            "--result",
            "v1:success",
            "--result",
            "v1:failure",
            "--result",
            "v2:success",
            "--result",
            "v2:success",
            "--min-samples",
            "2",
            "--win-delta",
            "0.2",
            "--root",
            str(skill_root),
        ],
    )
    assert result.exit_code == 0

    log_path = default_optimization_log_path(skill_root)
    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    last = entries[-1]
    assert last["action"] == "promote"
    assert last["reason"]
    assert last["metrics"]

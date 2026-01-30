from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from click.testing import CliRunner

from skillos.cli import cli
from skillos.suggestions import (
    SuggestionPreferences,
    preferences_store_from_env,
)


def test_cli_suggestions_dismissal_reduces_frequency() -> None:
    runner = CliRunner()

    with runner.isolated_filesystem():
        root = Path("skills_root")
        context_path = Path("context.json")
        due_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        context_path.write_text(
            json.dumps(
                [
                    {
                        "source": "calendar",
                        "summary": "Submit compliance report",
                        "due_at": due_at,
                    }
                ],
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
        preferences_store = preferences_store_from_env(root)
        preferences_store.save(
            SuggestionPreferences(
                opt_in=True,
                max_per_day=5,
                min_interval_minutes=0,
                cooldown_minutes_on_dismiss=120,
            )
        )

        run_result = runner.invoke(
            cli,
            [
                "suggestions",
                "run",
                "--root",
                str(root),
                "--context",
                str(context_path),
            ],
        )
        assert run_result.exit_code == 0
        lines = [line for line in run_result.output.splitlines() if line]
        assert lines
        assert lines[0].startswith("suggestion_created:")
        suggestion_id = lines[0].split(":", 1)[1].strip()

        dismiss_result = runner.invoke(
            cli,
            ["suggestions", "dismiss", suggestion_id, "--root", str(root)],
        )
        assert dismiss_result.exit_code == 0
        assert "suggestion_dismissed" in dismiss_result.output

        rerun = runner.invoke(
            cli,
            [
                "suggestions",
                "run",
                "--root",
                str(root),
                "--context",
                str(context_path),
            ],
        )
        assert rerun.exit_code == 0
        assert "no_suggestions" in rerun.output

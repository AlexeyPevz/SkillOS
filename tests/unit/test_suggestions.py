from datetime import datetime, timedelta, timezone

from skillos.context_monitor import ContextMonitor, ContextSignal
from skillos.scheduler import SuggestionScheduler
from skillos.suggestions import (
    SuggestionPreferences,
    SuggestionPreferencesStore,
    SuggestionRecord,
    SuggestionStore,
)


def test_opt_in_and_throttling(tmp_path) -> None:
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    preferences_store = SuggestionPreferencesStore(tmp_path / "prefs.json")
    suggestion_store = SuggestionStore(tmp_path / "suggestions.json")
    monitor = ContextMonitor(relevance_window_hours=24)
    scheduler = SuggestionScheduler(
        monitor,
        suggestion_store,
        preferences_store,
        now_provider=lambda: now,
    )
    signal = ContextSignal(
        source="calendar",
        summary="Quarterly review deadline",
        due_at=now + timedelta(hours=4),
    )

    preferences_store.save(SuggestionPreferences(opt_in=False))
    assert scheduler.run([signal]) == []
    assert suggestion_store.load() == []

    preferences_store.save(
        SuggestionPreferences(opt_in=True, max_per_day=1, min_interval_minutes=60)
    )
    suggestion_store.save(
        [
            SuggestionRecord(
                suggestion_id="existing",
                source="calendar",
                summary="Quarterly review deadline",
                message="Upcoming calendar: Quarterly review deadline",
                created_at=now - timedelta(minutes=30),
                status="created",
            )
        ]
    )
    assert scheduler.run([signal]) == []

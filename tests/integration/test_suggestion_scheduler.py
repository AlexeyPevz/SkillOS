from datetime import datetime, timedelta, timezone

from skillos.context_monitor import ContextMonitor, ContextSignal
from skillos.scheduler import SuggestionScheduler
from skillos.suggestions import (
    SuggestionPreferences,
    SuggestionPreferencesStore,
    SuggestionStore,
)


def test_scheduler_creates_suggestion_from_calendar(tmp_path) -> None:
    now = datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)
    preferences_store = SuggestionPreferencesStore(tmp_path / "prefs.json")
    suggestion_store = SuggestionStore(tmp_path / "suggestions.json")
    preferences_store.save(
        SuggestionPreferences(opt_in=True, max_per_day=3, min_interval_minutes=0)
    )
    monitor = ContextMonitor(relevance_window_hours=24)
    scheduler = SuggestionScheduler(
        monitor,
        suggestion_store,
        preferences_store,
        now_provider=lambda: now,
    )
    signals = [
        ContextSignal(
            source="calendar",
            summary="Budget review due",
            due_at=now + timedelta(hours=2),
        ),
        ContextSignal(
            source="calendar",
            summary="Roadmap update",
            due_at=now + timedelta(days=5),
        ),
    ]

    suggestions = scheduler.run(signals)
    assert len(suggestions) == 1
    stored = suggestion_store.load()
    assert len(stored) == 1
    assert stored[0].summary == "Budget review due"

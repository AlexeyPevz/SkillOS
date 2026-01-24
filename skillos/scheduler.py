from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Iterable
from uuid import uuid4

from skillos.context_monitor import ContextMonitor, ContextSignal
from skillos.suggestions import (
    SuggestionPreferences,
    SuggestionPreferencesStore,
    SuggestionRecord,
    SuggestionStore,
    _utc_now,
)


class SuggestionScheduler:
    def __init__(
        self,
        context_monitor: ContextMonitor,
        suggestion_store: SuggestionStore,
        preferences_store: SuggestionPreferencesStore,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._monitor = context_monitor
        self._store = suggestion_store
        self._preferences = preferences_store
        self._now = now_provider

    def run(self, signals: Iterable[ContextSignal]) -> list[SuggestionRecord]:
        preferences = self._preferences.load()
        if not preferences.opt_in:
            return []
        now = self._now()
        if preferences.snoozed_until and now < preferences.snoozed_until:
            return []
        relevant = self._monitor.find_relevant(list(signals), now)
        if not relevant:
            return []
        records = self._store.load()
        suggestions: list[SuggestionRecord] = []
        for signal in relevant:
            if not _within_limits(records, preferences, now):
                break
            suggestion = _build_suggestion(signal, now)
            records.append(suggestion)
            suggestions.append(suggestion)
        if suggestions:
            self._store.save(records)
        return suggestions


def _within_limits(
    records: list[SuggestionRecord],
    preferences: SuggestionPreferences,
    now: datetime,
) -> bool:
    if preferences.max_per_day <= 0:
        return False
    if preferences.min_interval_minutes > 0:
        last_created = _last_created_at(records)
        if last_created and now - last_created < timedelta(
            minutes=preferences.min_interval_minutes
        ):
            return False
    recent = _recent_records(records, now)
    if len(recent) >= preferences.max_per_day:
        return False
    return True


def _recent_records(
    records: list[SuggestionRecord], now: datetime
) -> list[SuggestionRecord]:
    cutoff = now - timedelta(days=1)
    return [record for record in records if record.created_at >= cutoff]


def _last_created_at(records: list[SuggestionRecord]) -> datetime | None:
    if not records:
        return None
    return max(record.created_at for record in records)


def _build_suggestion(signal: ContextSignal, now: datetime) -> SuggestionRecord:
    message = f"Upcoming {signal.source}: {signal.summary}"
    return SuggestionRecord(
        suggestion_id=uuid4().hex,
        source=signal.source,
        summary=signal.summary,
        message=message,
        created_at=now,
        status="created",
    )

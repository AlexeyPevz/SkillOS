from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from skillos.suggestions import (
    SuggestionPreferencesStore,
    SuggestionRecord,
    SuggestionStore,
    _utc_now,
)


class NotificationCenter:
    def __init__(
        self,
        suggestion_store: SuggestionStore,
        preferences_store: SuggestionPreferencesStore,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = suggestion_store
        self._preferences = preferences_store
        self._now = now_provider

    def dismiss(self, suggestion_id: str) -> SuggestionRecord | None:
        records = self._store.load()
        now = self._now()
        dismissed: SuggestionRecord | None = None
        for record in records:
            if record.suggestion_id == suggestion_id:
                record.status = "dismissed"
                record.dismissed_at = now
                dismissed = record
                break
        if dismissed is None:
            return None
        self._store.save(records)

        preferences = self._preferences.load()
        if preferences.cooldown_minutes_on_dismiss > 0:
            preferences.snoozed_until = now + timedelta(
                minutes=preferences.cooldown_minutes_on_dismiss
            )
            self._preferences.save(preferences)
        return dismissed

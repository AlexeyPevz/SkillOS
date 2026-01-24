from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


class ContextMonitorError(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    return _ensure_utc(parsed)


@dataclass
class ContextSignal:
    source: str
    summary: str
    due_at: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "summary": self.summary,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ContextSignal":
        source = payload.get("source")
        summary = payload.get("summary")
        if not source or not summary:
            raise ContextMonitorError("context_signal_missing_fields")
        raw_due_at = payload.get("due_at")
        due_at = _parse_datetime(str(raw_due_at)) if raw_due_at else None
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return cls(
            source=str(source),
            summary=str(summary),
            due_at=due_at,
            metadata={str(key): str(value) for key, value in metadata.items()},
        )


def load_context_signals(path: Path) -> list[ContextSignal]:
    if not Path(path).exists():
        return []
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContextMonitorError(f"invalid_context_json: {exc}") from exc
    if not isinstance(raw, list):
        raise ContextMonitorError("context_payload_must_be_list")
    signals: list[ContextSignal] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ContextMonitorError("context_signal_must_be_object")
        signals.append(ContextSignal.from_dict(item))
    return signals


class ContextMonitor:
    def __init__(self, relevance_window_hours: int = 24) -> None:
        self._window = timedelta(hours=relevance_window_hours)

    def find_relevant(
        self, signals: list[ContextSignal], now: datetime | None = None
    ) -> list[ContextSignal]:
        current = _ensure_utc(now) if now else _utc_now()
        window_end = current + self._window
        relevant: list[ContextSignal] = []
        for signal in signals:
            if signal.due_at is None:
                relevant.append(signal)
                continue
            due_at = _ensure_utc(signal.due_at)
            if current <= due_at <= window_end:
                relevant.append(signal)
        return relevant

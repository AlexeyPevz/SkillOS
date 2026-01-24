from datetime import datetime, timedelta, timezone
from pathlib import Path

from skillos.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerStore,
    default_circuit_breaker_path,
)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now = self._now + timedelta(seconds=seconds)


def test_circuit_breaker_opens_and_blocks(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store = CircuitBreakerStore(
        default_circuit_breaker_path(tmp_path),
        now_provider=clock.now,
    )
    breaker = CircuitBreaker(
        store,
        CircuitBreakerConfig(
            failure_threshold=2,
            window_seconds=60,
            open_seconds=30,
            half_open_max_attempts=1,
        ),
    )

    assert breaker.allow("travel/search_flights").allowed is True
    breaker.record_failure("travel/search_flights")
    breaker.record_failure("travel/search_flights")
    blocked = breaker.allow("travel/search_flights")
    assert blocked.allowed is False
    assert blocked.reason == "circuit_open"


def test_circuit_breaker_half_open_resets_on_success(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    store = CircuitBreakerStore(
        default_circuit_breaker_path(tmp_path),
        now_provider=clock.now,
    )
    breaker = CircuitBreaker(
        store,
        CircuitBreakerConfig(
            failure_threshold=1,
            window_seconds=60,
            open_seconds=10,
            half_open_max_attempts=1,
        ),
    )

    breaker.record_failure("travel/search_flights")
    assert breaker.allow("travel/search_flights").allowed is False

    clock.advance(11)
    half_open = breaker.allow("travel/search_flights")
    assert half_open.allowed is True
    breaker.record_success("travel/search_flights")
    assert breaker.allow("travel/search_flights").allowed is True

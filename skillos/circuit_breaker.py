from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Callable

from skillos.storage import atomic_write_text, file_lock
from skillos.tenancy import resolve_tenant_root


DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_WINDOW_SECONDS = 300
DEFAULT_OPEN_SECONDS = 300
DEFAULT_HALF_OPEN_MAX = 1


def default_circuit_breaker_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "runtime" / "circuit_breaker.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_utc(value).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return _ensure_utc(parsed)


@dataclass(frozen=True)
class CircuitBreakerConfig:
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    window_seconds: int = DEFAULT_WINDOW_SECONDS
    open_seconds: int = DEFAULT_OPEN_SECONDS
    half_open_max_attempts: int = DEFAULT_HALF_OPEN_MAX


def circuit_breaker_config_from_env() -> CircuitBreakerConfig:
    return CircuitBreakerConfig(
        failure_threshold=_env_int(
            "SKILLOS_CIRCUIT_FAILURE_THRESHOLD",
            DEFAULT_FAILURE_THRESHOLD,
        ),
        window_seconds=_env_int(
            "SKILLOS_CIRCUIT_WINDOW_SECONDS",
            DEFAULT_WINDOW_SECONDS,
        ),
        open_seconds=_env_int(
            "SKILLOS_CIRCUIT_OPEN_SECONDS",
            DEFAULT_OPEN_SECONDS,
        ),
        half_open_max_attempts=_env_int(
            "SKILLOS_CIRCUIT_HALF_OPEN_MAX",
            DEFAULT_HALF_OPEN_MAX,
        ),
    )


@dataclass
class CircuitState:
    state: str = "closed"
    failure_count: int = 0
    last_failure_at: datetime | None = None
    opened_at: datetime | None = None
    half_open_attempts: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure_at": _format_datetime(self.last_failure_at),
            "opened_at": _format_datetime(self.opened_at),
            "half_open_attempts": self.half_open_attempts,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "CircuitState":
        return cls(
            state=str(payload.get("state", "closed")),
            failure_count=int(payload.get("failure_count", 0)),
            last_failure_at=_parse_datetime(
                str(payload.get("last_failure_at"))
            )
            if payload.get("last_failure_at")
            else None,
            opened_at=_parse_datetime(str(payload.get("opened_at")))
            if payload.get("opened_at")
            else None,
            half_open_attempts=int(payload.get("half_open_attempts", 0)),
        )


@dataclass(frozen=True)
class CircuitDecision:
    allowed: bool
    state: str
    reason: str | None = None


class CircuitBreakerStore:
    def __init__(
        self,
        path: Path,
        *,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.path = Path(path)
        self._now = now_provider

    def load(self) -> dict[str, CircuitState]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        raw_states = raw.get("states", raw)
        if not isinstance(raw_states, dict):
            return {}
        states: dict[str, CircuitState] = {}
        for skill_id, payload in raw_states.items():
            if isinstance(payload, dict):
                states[str(skill_id)] = CircuitState.from_dict(payload)
        return states

    def save(self, states: dict[str, CircuitState]) -> None:
        payload = {"states": {key: value.to_dict() for key, value in states.items()}}
        with file_lock(self.path):
            atomic_write_text(
                self.path,
                json.dumps(payload, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )

    def now(self) -> datetime:
        return _ensure_utc(self._now())


class CircuitBreaker:
    def __init__(
        self,
        store: CircuitBreakerStore,
        config: CircuitBreakerConfig | None = None,
    ) -> None:
        self._store = store
        self._config = config or CircuitBreakerConfig()

    def allow(self, skill_id: str) -> CircuitDecision:
        states = self._store.load()
        state = states.get(skill_id, CircuitState())
        now = self._store.now()

        if state.state == "open":
            if self._open_expired(state, now):
                state = CircuitState(state="half_open")
                states[skill_id] = state
                self._store.save(states)
                return CircuitDecision(allowed=True, state=state.state)
            return CircuitDecision(
                allowed=False, state=state.state, reason="circuit_open"
            )

        if state.state == "half_open":
            if state.half_open_attempts >= self._config.half_open_max_attempts:
                return CircuitDecision(
                    allowed=False, state=state.state, reason="circuit_half_open"
                )
            state.half_open_attempts += 1
            states[skill_id] = state
            self._store.save(states)
            return CircuitDecision(allowed=True, state=state.state)

        if self._failure_window_expired(state, now):
            state.failure_count = 0
            state.last_failure_at = None
            states[skill_id] = state
            self._store.save(states)

        return CircuitDecision(allowed=True, state=state.state)

    def record_success(self, skill_id: str) -> None:
        states = self._store.load()
        states[skill_id] = CircuitState()
        self._store.save(states)

    def record_failure(self, skill_id: str) -> None:
        states = self._store.load()
        state = states.get(skill_id, CircuitState())
        now = self._store.now()

        if state.state == "open":
            return
        if state.state == "half_open":
            state = CircuitState(
                state="open",
                failure_count=self._config.failure_threshold,
                last_failure_at=now,
                opened_at=now,
            )
            states[skill_id] = state
            self._store.save(states)
            return

        if self._failure_window_expired(state, now):
            state.failure_count = 0
        state.failure_count += 1
        state.last_failure_at = now
        if state.failure_count >= self._config.failure_threshold:
            state.state = "open"
            state.opened_at = now
        states[skill_id] = state
        self._store.save(states)

    def _open_expired(self, state: CircuitState, now: datetime) -> bool:
        opened_at = state.opened_at or now
        return now >= opened_at + timedelta(seconds=self._config.open_seconds)

    def _failure_window_expired(self, state: CircuitState, now: datetime) -> bool:
        last_failure = state.last_failure_at
        if not last_failure:
            return False
        return now - last_failure > timedelta(seconds=self._config.window_seconds)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default

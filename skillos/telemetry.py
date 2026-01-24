from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Iterable
from uuid import uuid4

from skillos.routing import RoutingResult, SkillCandidate
from skillos.tenancy import resolve_tenant_root


class LogSchemaError(ValueError):
    pass


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

_BASE_REQUIRED_FIELDS = {"request_id"}
_EVENT_REQUIRED_FIELDS: dict[str, set[str]] = {
    "request_received": {"query_hash", "query_length", "token_count"},
    "routing_candidates": {"candidates", "routing_latency_ms"},
    "routing_decision": {"skill_id", "confidence", "status", "reason"},
    "budget_check": {
        "allowed",
        "reason",
        "model",
        "estimated_cost",
        "remaining_daily",
        "remaining_monthly",
    },
    "policy_decision": {"allowed", "policy_id"},
    "permission_decision": {
        "allowed",
        "policy_id",
        "role",
        "skill_id",
        "required_permissions",
    },
    "execution_result": {"status", "duration_ms"},
    "composition_step": {"status", "duration_ms", "skill_id", "step_id", "order"},
    "skill_selected": {"skill_id", "confidence", "status"},
    "no_skill_found": {"query_hash"},
    "feedback_received": {"expected_skill_id", "correction", "source"},
    "schedule_due": {"schedule_id", "skill_id", "due_at", "lag_ms"},
    "schedule_started": {"schedule_id", "skill_id", "due_at", "lag_ms"},
    "schedule_completed": {"schedule_id", "skill_id", "duration_ms", "status"},
    "schedule_failed": {"schedule_id", "skill_id", "duration_ms", "error_class"},
    "job_enqueued": {"job_id", "skill_id", "status", "max_retries"},
    "job_started": {"job_id", "skill_id", "status", "retries", "max_retries"},
    "job_succeeded": {"job_id", "skill_id", "status", "duration_ms"},
    "job_failed": {
        "job_id",
        "skill_id",
        "status",
        "error_class",
        "retries",
        "max_retries",
    },
    "pipeline_step": {"status", "duration_ms", "step_id", "order", "group"},
    "deprecated_skill_used": {"skill_id"},
    "idempotency_skipped": {
        "source",
        "skill_id",
        "idempotency_key",
        "expires_at",
    },
    "attachments_ingested": {"count", "total_bytes", "attachments"},
    "integration_call": {"connector_id", "connector_type", "status", "latency_ms"},
    "webhook_received": {"trigger_id", "skill_id", "status", "status_code"},
}


def default_log_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "logs" / "execution.log"


def default_metrics_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "logs" / "metrics_summary.json"


def new_request_id() -> str:
    return uuid4().hex


def hash_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def token_count(query: str) -> int:
    return len(_TOKEN_RE.findall(query))


def _redact_string(value: str) -> str:
    redacted = _EMAIL_RE.sub("[REDACTED]", value)
    redacted = _PHONE_RE.sub("[REDACTED]", redacted)
    return redacted


def _is_secret_value(value: object) -> bool:
    return value.__class__.__name__ == "SecretValue" and hasattr(value, "value")


def redact_pii(value: object) -> object:
    if _is_secret_value(value):
        return "[REDACTED]"
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        return {key: redact_pii(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_pii(item) for item in value]
    return value


def routing_decision_reason(result: RoutingResult) -> str:
    if result.status == "no_skill_found":
        return "no_candidates"
    if result.status == "low_confidence":
        return "low_confidence"
    return "confidence_above_threshold"


def _format_candidates(candidates: Iterable[SkillCandidate]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for candidate in candidates:
        payload.append(
            {
                "skill_id": candidate.skill_id,
                "score": candidate.score,
                "keyword_score": candidate.keyword_score,
                "semantic_score": candidate.semantic_score,
            }
        )
    return payload


@dataclass(frozen=True)
class RoutingTelemetry:
    result: RoutingResult
    routing_latency_ms: float


@dataclass
class EventLogger:
    path: Path
    request_id: str | None = None

    def log(self, event: str, **fields: object) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload_fields = dict(fields)
        if "request_id" not in payload_fields:
            if self.request_id is None:
                raise LogSchemaError("request_id is required for log events")
            payload_fields["request_id"] = self.request_id

        required_fields = _BASE_REQUIRED_FIELDS | _EVENT_REQUIRED_FIELDS.get(
            event, set()
        )
        missing = required_fields.difference(payload_fields)
        if missing:
            raise LogSchemaError(
                f"Missing required fields for {event}: {sorted(missing)}"
            )

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **redact_pii(payload_fields),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def log_job_enqueued(
    logger: EventLogger,
    *,
    job_id: str,
    skill_id: str,
    status: str,
    max_retries: int,
) -> None:
    logger.log(
        "job_enqueued",
        job_id=job_id,
        skill_id=skill_id,
        status=status,
        max_retries=max_retries,
    )


def log_job_started(
    logger: EventLogger,
    *,
    job_id: str,
    skill_id: str,
    status: str,
    retries: int,
    max_retries: int,
) -> None:
    logger.log(
        "job_started",
        job_id=job_id,
        skill_id=skill_id,
        status=status,
        retries=retries,
        max_retries=max_retries,
    )


def log_job_succeeded(
    logger: EventLogger,
    *,
    job_id: str,
    skill_id: str,
    status: str,
    duration_ms: float,
) -> None:
    logger.log(
        "job_succeeded",
        job_id=job_id,
        skill_id=skill_id,
        status=status,
        duration_ms=duration_ms,
    )


def log_job_failed(
    logger: EventLogger,
    *,
    job_id: str,
    skill_id: str,
    status: str,
    error_class: str,
    retries: int,
    max_retries: int,
    next_run_at: str | None,
    retrying: bool,
) -> None:
    logger.log(
        "job_failed",
        job_id=job_id,
        skill_id=skill_id,
        status=status,
        error_class=error_class,
        retries=retries,
        max_retries=max_retries,
        next_run_at=next_run_at,
        retrying=retrying,
    )


def log_schedule_due(
    logger: EventLogger,
    *,
    schedule_id: str,
    skill_id: str,
    run_at: str | None,
    due_at: str | None,
    lag_ms: float,
    retries: int,
    max_retries: int,
) -> None:
    logger.log(
        "schedule_due",
        schedule_id=schedule_id,
        skill_id=skill_id,
        run_at=run_at,
        due_at=due_at,
        lag_ms=lag_ms,
        retries=retries,
        max_retries=max_retries,
    )


def log_schedule_started(
    logger: EventLogger,
    *,
    schedule_id: str,
    skill_id: str,
    run_at: str | None,
    due_at: str | None,
    lag_ms: float,
    retries: int,
    max_retries: int,
) -> None:
    logger.log(
        "schedule_started",
        schedule_id=schedule_id,
        skill_id=skill_id,
        run_at=run_at,
        due_at=due_at,
        lag_ms=lag_ms,
        retries=retries,
        max_retries=max_retries,
    )


def log_schedule_completed(
    logger: EventLogger,
    *,
    schedule_id: str,
    skill_id: str,
    duration_ms: float,
    status: str,
    retries: int,
    max_retries: int,
) -> None:
    logger.log(
        "schedule_completed",
        schedule_id=schedule_id,
        skill_id=skill_id,
        duration_ms=duration_ms,
        status=status,
        retries=retries,
        max_retries=max_retries,
    )


def log_schedule_failed(
    logger: EventLogger,
    *,
    schedule_id: str,
    skill_id: str,
    duration_ms: float,
    error_class: str,
    retries: int,
    max_retries: int,
) -> None:
    logger.log(
        "schedule_failed",
        schedule_id=schedule_id,
        skill_id=skill_id,
        duration_ms=duration_ms,
        error_class=error_class,
        retries=retries,
        max_retries=max_retries,
    )


def route_with_telemetry(
    query: str,
    router,
    logger: EventLogger,
    request_id: str,
    *,
    tags: list[str] | None = None,
    routing_cache=None,
) -> RoutingTelemetry:
    start = time.perf_counter()
    result = None
    cache_hit = False
    if routing_cache is not None:
        result = routing_cache.get(query, tags)
        cache_hit = result is not None
    if result is None:
        result = router.route(query, tags=tags)
        if routing_cache is not None:
            routing_cache.set(query, tags, result)
    routing_latency_ms = (time.perf_counter() - start) * 1000

    logger.log(
        "routing_candidates",
        request_id=request_id,
        candidates=_format_candidates(result.candidates),
        routing_latency_ms=routing_latency_ms,
        cache_hit=cache_hit,
    )
    logger.log(
        "routing_decision",
        request_id=request_id,
        skill_id=result.skill_id,
        confidence=result.confidence,
        status=result.status,
        reason=routing_decision_reason(result),
        alternatives=result.alternatives,
    )

    return RoutingTelemetry(result=result, routing_latency_ms=routing_latency_ms)

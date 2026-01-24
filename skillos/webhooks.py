from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import time

from skillos.attachments import AttachmentError, AttachmentReference, ingest_attachments
from skillos.connectors import SecretResolutionError, SecretResolver, SecretsStore, default_secrets_path
from skillos.idempotency import (
    IdempotencyDecision,
    idempotency_store_from_env,
    idempotency_ttl_from_env,
)
from skillos.jobs import job_store_from_env
from skillos.routing import to_internal_id
from skillos.telemetry import (
    EventLogger,
    default_log_path,
    log_job_enqueued,
    new_request_id,
)
from skillos.tenancy import resolve_tenant_root


class WebhookError(ValueError):
    pass


class WebhookTriggerError(WebhookError):
    pass


class WebhookPayloadError(WebhookError):
    pass


class WebhookSignatureError(WebhookError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class WebhookTrigger:
    trigger_id: str
    skill_id: str


@dataclass(frozen=True)
class WebhookHandleResult:
    status: str
    trigger_id: str
    skill_id: str
    job_id: str | None
    idempotency_key: str | None
    expires_at: str | None


DEFAULT_SIGNATURE_TTL_SECONDS = 300


def default_webhook_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "triggers" / "webhooks.json"


def load_webhook_triggers(path: Path) -> dict[str, WebhookTrigger]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("webhooks", raw.get("triggers", raw))
    if not isinstance(items, list):
        raise WebhookTriggerError("invalid_trigger_format")
    triggers: dict[str, WebhookTrigger] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        trigger_id = str(item.get("id") or item.get("trigger_id") or "").strip()
        skill_id = str(item.get("skill_id") or "").strip()
        if not trigger_id or not skill_id:
            continue
        triggers[trigger_id] = WebhookTrigger(
            trigger_id=trigger_id,
            skill_id=skill_id,
        )
    return triggers


def resolve_webhook_trigger(path: Path, trigger_id: str) -> WebhookTrigger:
    triggers = load_webhook_triggers(path)
    trigger = triggers.get(trigger_id)
    if trigger is None:
        raise WebhookTriggerError("trigger_not_found")
    return trigger


def load_webhook_payload(path: Path) -> tuple[dict[str, object], str]:
    raw = path.read_text(encoding="utf-8")
    payload = _parse_webhook_payload(raw)
    return payload, raw


def _parse_webhook_payload(raw: str) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WebhookPayloadError("invalid_payload") from exc
    if not isinstance(payload, dict):
        raise WebhookPayloadError("invalid_payload")
    return payload


def handle_webhook_event(
    trigger_id: str,
    payload_path: Path,
    root_path: Path,
    *,
    signature: str | None = None,
    idempotency_key: str | None = None,
    log_path: Path | None = None,
    ttl_seconds: int | None = None,
    signature_ttl_seconds: int | None = None,
) -> WebhookHandleResult:
    trigger = resolve_webhook_trigger(default_webhook_path(root_path), trigger_id)
    raw_payload = payload_path.read_text(encoding="utf-8")
    request_id = new_request_id()
    logger = EventLogger(log_path or default_log_path(root_path), request_id=request_id)

    try:
        _validate_signature(
            signature,
            root_path,
            raw_payload,
            ttl_seconds=signature_ttl_seconds,
        )
    except WebhookSignatureError as exc:
        logger.log(
            "webhook_received",
            trigger_id=trigger.trigger_id,
            skill_id=trigger.skill_id,
            status="rejected",
            status_code=exc.status_code,
            reason=str(exc),
        )
        raise

    from skillos.rate_limit import rate_limiter_from_env
    from skillos.storage_backend import resolve_tenant_id
    
    tenant_id = resolve_tenant_id(root_path)
    limiter = rate_limiter_from_env()
    # Scoped to tenant to prevent collision
    rl_key = f"tenant:{tenant_id}:webhook:{trigger_id}"
    
    if not limiter.check_and_consume(rl_key):
        logger.log(
            "webhook_received",
            trigger_id=trigger.trigger_id,
            skill_id=trigger.skill_id,
            status="rate_limited",
            status_code=429,
        )
        raise WebhookTriggerError("rate_limit_exceeded")

    try:
        payload = _parse_webhook_payload(raw_payload)
    except WebhookPayloadError as exc:
        logger.log(
            "webhook_received",
            trigger_id=trigger.trigger_id,
            skill_id=trigger.skill_id,
            status="rejected",
            status_code=400,
            reason=str(exc),
        )
        raise

    logger.log(
        "webhook_received",
        trigger_id=trigger.trigger_id,
        skill_id=trigger.skill_id,
        status="accepted",
        status_code=200,
    )

    resolved_key = _resolve_idempotency_key(payload, idempotency_key)
    decision = None
    if resolved_key:
        decision = _check_idempotency(
            resolved_key,
            trigger,
            root_path,
            ttl_seconds=ttl_seconds,
        )
        if not decision.allowed:
            expires_at = decision.expires_at.isoformat() if decision.expires_at else None
            logger.log(
                "idempotency_skipped",
                source="webhook",
                skill_id=trigger.skill_id,
                idempotency_key=resolved_key,
                expires_at=expires_at,
            )
            return WebhookHandleResult(
                status="skipped",
                trigger_id=trigger.trigger_id,
                skill_id=trigger.skill_id,
                job_id=None,
                idempotency_key=resolved_key,
                expires_at=expires_at,
            )

    try:
        attachments = ingest_attachments(
            payload.get("attachments"),
            root_path,
            request_id=request_id,
        )
    except AttachmentError as exc:
        raise WebhookPayloadError(str(exc)) from exc

    if attachments:
        logger.log(
            "attachments_ingested",
            count=len(attachments),
            total_bytes=sum(attachment.size_bytes for attachment in attachments),
            attachments=[attachment.to_dict() for attachment in attachments],
        )

    job_payload = _resolve_job_payload(payload, raw_payload, attachments)
    store = job_store_from_env(root_path)
    record = store.enqueue(
        to_internal_id(trigger.skill_id),
        payload=job_payload,
        max_retries=0,
    )
    log_job_enqueued(
        logger,
        job_id=record.job_id,
        skill_id=record.skill_id,
        status=record.status,
        max_retries=record.max_retries,
    )
    expires_at = decision.expires_at.isoformat() if decision and decision.expires_at else None
    return WebhookHandleResult(
        status="enqueued",
        trigger_id=trigger.trigger_id,
        skill_id=trigger.skill_id,
        job_id=record.job_id,
        idempotency_key=resolved_key,
        expires_at=expires_at,
    )


def build_signature_header(
    secret: str, raw_body: str, *, timestamp: int | None = None
) -> str:
    ts = int(timestamp if timestamp is not None else time.time())
    signature = compute_signature(secret, ts, raw_body)
    return f"t={ts},v1={signature}"


def compute_signature(secret: str, timestamp: int, raw_body: str) -> str:
    base = f"{timestamp}.{raw_body}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()


def _validate_signature(
    signature_header: str | None,
    root_path: Path,
    raw_body: str,
    *,
    ttl_seconds: int | None = None,
) -> None:
    secret = _resolve_webhook_secret(root_path)
    allow_unsigned = _allow_unsigned_webhooks()
    if not secret and not signature_header:
        if allow_unsigned:
            return
        raise WebhookSignatureError("signature_required", 401)
    if not secret:
        raise WebhookSignatureError("signature_secret_missing", 401)
    if not signature_header:
        raise WebhookSignatureError("signature_missing", 401)
    timestamp, signature = _parse_signature_header(signature_header)
    ttl = DEFAULT_SIGNATURE_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    now = int(time.time())
    if ttl > 0 and abs(now - timestamp) > ttl:
        raise WebhookSignatureError("signature_expired", 410)
    expected = compute_signature(secret, timestamp, raw_body)
    if not hmac.compare_digest(signature, expected):
        raise WebhookSignatureError("invalid_signature", 401)


def _parse_signature_header(value: str) -> tuple[int, str]:
    header = value.strip()
    if header.lower().startswith("x-skillos-signature:"):
        header = header.split(":", 1)[1].strip()
    pairs: dict[str, str] = {}
    for part in header.split(","):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        pairs[key.strip()] = val.strip()
    if "t" not in pairs or "v1" not in pairs:
        raise WebhookSignatureError("invalid_signature", 401)
    try:
        timestamp = int(pairs["t"])
    except ValueError as exc:
        raise WebhookSignatureError("invalid_signature", 401) from exc
    signature = pairs["v1"]
    if not signature:
        raise WebhookSignatureError("invalid_signature", 401)
    return timestamp, signature


def _resolve_webhook_secret(root_path: Path) -> str | None:
    resolver = SecretResolver(store=SecretsStore(default_secrets_path(root_path)))
    try:
        secret = resolver.resolve("secret", integration="webhook")
    except SecretResolutionError:
        return None
    return secret.value


def _allow_unsigned_webhooks() -> bool:
    raw = os.getenv("SKILLOS_WEBHOOK_ALLOW_UNSIGNED")
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_idempotency_key(
    payload: dict[str, object],
    override: str | None,
) -> str | None:
    if override:
        return str(override)
    key = payload.get("idempotency_key")
    if key is None:
        return None
    return str(key)


def _resolve_job_payload(
    payload: dict[str, object],
    raw: str,
    attachments: list[AttachmentReference],
) -> str:
    if attachments:
        return _build_attachment_payload(payload, attachments)
    if "payload" in payload:
        value = payload["payload"]
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=True)
    return raw


def _build_attachment_payload(
    payload: dict[str, object],
    attachments: list[AttachmentReference],
) -> str:
    base_payload = _resolve_base_payload(payload)
    payload_with_attachments = {
        "payload": base_payload,
        "attachments": [attachment.to_dict() for attachment in attachments],
    }
    return json.dumps(payload_with_attachments, ensure_ascii=True)


def _resolve_base_payload(payload: dict[str, object]) -> object:
    if "payload" in payload:
        return payload["payload"]
    return {
        key: value
        for key, value in payload.items()
        if key not in {"attachments", "idempotency_key"}
    }


def _check_idempotency(
    idempotency_key: str,
    trigger: WebhookTrigger,
    root_path: Path,
    *,
    ttl_seconds: int | None = None,
) -> IdempotencyDecision:
    store = idempotency_store_from_env(root_path)
    ttl = ttl_seconds if ttl_seconds is not None else idempotency_ttl_from_env()
    return store.check_and_record(
        "webhook",
        trigger.skill_id,
        idempotency_key,
        ttl_seconds=ttl,
    )

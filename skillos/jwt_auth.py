from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import hmac
import json
import os
import re
import time
from typing import Mapping


class JwtValidationError(ValueError):
    pass


_JWT_TOKEN_ENV = "SKILLOS_JWT_TOKEN"
_ALG_PATTERN = re.compile(r"^HS(256|384|512)$")
_DEFAULT_CLOCK_SKEW = 60


@dataclass(frozen=True)
class JwtConfig:
    secret: str | None = None
    issuer: str | None = None
    audience: str | None = None
    algorithm: str = "HS256"
    clock_skew_seconds: int = _DEFAULT_CLOCK_SKEW
    require_exp: bool = True
    allow_unverified: bool = False


@dataclass(frozen=True)
class JwtClaims:
    subject: str | None
    tenant_id: str | None
    role: str | None
    permissions: list[str]
    claims: dict[str, object]
    verified: bool

    @property
    def attributes(self) -> dict[str, object]:
        payload = {key: value for key, value in self.claims.items() if key != "role"}
        if self.subject is not None:
            payload.setdefault("subject", self.subject)
        if self.tenant_id is not None:
            payload.setdefault("tenant_id", self.tenant_id)
        if self.permissions:
            payload.setdefault("permissions", list(self.permissions))
        payload.setdefault("verified", self.verified)
        return payload


def jwt_config_from_env(env: Mapping[str, str] | None = None) -> JwtConfig:
    env_map = env or os.environ
    return JwtConfig(
        secret=_env_value(env_map, "SKILLOS_JWT_SECRET"),
        issuer=_env_value(env_map, "SKILLOS_JWT_ISSUER"),
        audience=_env_value(env_map, "SKILLOS_JWT_AUDIENCE"),
        algorithm=_env_value(env_map, "SKILLOS_JWT_ALGORITHM") or "HS256",
        clock_skew_seconds=_env_int(
            env_map,
            "SKILLOS_JWT_CLOCK_SKEW_SECONDS",
            _DEFAULT_CLOCK_SKEW,
        ),
        require_exp=_env_bool(env_map, "SKILLOS_JWT_REQUIRE_EXP", True),
        allow_unverified=_resolve_allow_unverified(env_map),
    )


def _resolve_allow_unverified(env_map: Mapping[str, str]) -> bool:
    is_prod = _env_value(env_map, "SKILLOS_ENV") in ("prod", "production")
    requested = _env_bool(env_map, "SKILLOS_JWT_ALLOW_UNVERIFIED", False)
    if is_prod and requested:
        # Log warning here in real app, but for now just enforce security
        return False
    return requested


def jwt_token_from_env(env: Mapping[str, str] | None = None) -> str | None:
    env_map = env or os.environ
    raw = env_map.get(_JWT_TOKEN_ENV)
    if not raw:
        return None
    token = raw.strip()
    return token or None


def decode_jwt(token: str, config: JwtConfig | None = None) -> JwtClaims:
    if not token or not isinstance(token, str):
        raise JwtValidationError("jwt_missing")
    segments = token.strip().split(".")
    if len(segments) != 3:
        raise JwtValidationError("jwt_invalid_format")

    header = _decode_segment(segments[0], "header")
    payload = _decode_segment(segments[1], "payload")
    signature = _decode_bytes(segments[2], "signature")

    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise JwtValidationError("jwt_invalid_payload")

    config = config or jwt_config_from_env()
    algorithm = str(header.get("alg") or "").upper()
    if not algorithm or algorithm == "NONE":
        raise JwtValidationError("jwt_alg_missing")
    if not _ALG_PATTERN.match(algorithm):
        raise JwtValidationError("jwt_alg_unsupported")
    if algorithm != config.algorithm.upper():
        raise JwtValidationError("jwt_alg_mismatch")

    verified = _verify_signature(
        segments[0],
        segments[1],
        signature,
        algorithm,
        config,
    )
    _validate_claims(payload, config)

    subject = _extract_string(payload.get("sub"))
    tenant_id = _extract_tenant_id(payload)
    role = _extract_role(payload)
    permissions = _extract_permissions(payload)

    return JwtClaims(
        subject=subject,
        tenant_id=tenant_id,
        role=role,
        permissions=permissions,
        claims=dict(payload),
        verified=verified,
    )


def _verify_signature(
    header_segment: str,
    payload_segment: str,
    signature: bytes,
    algorithm: str,
    config: JwtConfig,
) -> bool:
    secret = (config.secret or "").strip()
    if not secret:
        if config.allow_unverified:
            return False
        raise JwtValidationError("jwt_secret_missing")

    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    digest = _hash_for_alg(algorithm)
    expected = hmac.new(secret.encode("utf-8"), signing_input, digest).digest()
    if not hmac.compare_digest(expected, signature):
        raise JwtValidationError("jwt_signature_invalid")
    return True


def _hash_for_alg(algorithm: str):
    if algorithm == "HS256":
        return hashlib.sha256
    if algorithm == "HS384":
        return hashlib.sha384
    if algorithm == "HS512":
        return hashlib.sha512
    raise JwtValidationError("jwt_alg_unsupported")


def _validate_claims(payload: dict[str, object], config: JwtConfig) -> None:
    now = time.time()
    skew = max(0, int(config.clock_skew_seconds))

    exp = payload.get("exp")
    if exp is None:
        if config.require_exp:
            raise JwtValidationError("jwt_exp_missing")
    else:
        exp_ts = _as_timestamp(exp, "exp")
        if now > exp_ts + skew:
            raise JwtValidationError("jwt_expired")

    nbf = payload.get("nbf")
    if nbf is not None:
        nbf_ts = _as_timestamp(nbf, "nbf")
        if now + skew < nbf_ts:
            raise JwtValidationError("jwt_not_active")

    if config.issuer:
        issuer = _extract_string(payload.get("iss"))
        if issuer != config.issuer:
            raise JwtValidationError("jwt_issuer_invalid")

    if config.audience:
        audience = payload.get("aud")
        if isinstance(audience, str):
            allowed = audience == config.audience
        elif isinstance(audience, list):
            allowed = config.audience in [str(item) for item in audience]
        else:
            allowed = False
        if not allowed:
            raise JwtValidationError("jwt_audience_invalid")


def _as_timestamp(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise JwtValidationError(f"jwt_{field}_invalid")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise JwtValidationError(f"jwt_{field}_invalid") from exc
    raise JwtValidationError(f"jwt_{field}_invalid")


def _extract_tenant_id(payload: dict[str, object]) -> str | None:
    for key in ("tenant_id", "tenant", "tid"):
        value = _extract_string(payload.get(key))
        if value:
            return value
    return None


def _extract_role(payload: dict[str, object]) -> str | None:
    value = _extract_string(payload.get("role"))
    if value:
        return value
    raw_roles = payload.get("roles")
    if isinstance(raw_roles, (list, tuple)):
        for item in raw_roles:
            role = _extract_string(item)
            if role:
                return role
    return None


def _extract_permissions(payload: dict[str, object]) -> list[str]:
    permissions = _normalize_string_list(payload.get("permissions"))
    if permissions:
        return permissions
    scopes = _normalize_string_list(payload.get("scopes"))
    if scopes:
        return scopes
    scope = _extract_string(payload.get("scope"))
    if not scope:
        return []
    parts = [part.strip() for part in re.split(r"[\\s,]+", scope) if part.strip()]
    return parts


def _normalize_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [item for item in [value.strip()] if item]
    if isinstance(value, (list, tuple)):
        return [item for item in (_extract_string(item) for item in value) if item]
    return []


def _extract_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decode_segment(segment: str, name: str) -> dict[str, object]:
    raw = _decode_bytes(segment, name)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JwtValidationError(f"jwt_{name}_invalid") from exc
    if not isinstance(payload, dict):
        raise JwtValidationError(f"jwt_{name}_invalid")
    return payload


def _decode_bytes(segment: str, name: str) -> bytes:
    if not isinstance(segment, str) or not segment:
        raise JwtValidationError(f"jwt_{name}_invalid")
    padded = segment + "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise JwtValidationError(f"jwt_{name}_invalid") from exc


def _env_value(env_map: Mapping[str, str], key: str) -> str | None:
    raw = env_map.get(key)
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _env_bool(env_map: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env_map.get(key)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return default


def _env_int(env_map: Mapping[str, str], key: str, default: int) -> int:
    raw = env_map.get(key)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default

import base64
import hashlib
import hmac
import json
import time

import pytest

from skillos.jwt_auth import JwtConfig, JwtValidationError, decode_jwt


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _sign(alg: str, secret: str, data: bytes) -> bytes:
    if alg == "HS256":
        digest = hashlib.sha256
    elif alg == "HS384":
        digest = hashlib.sha384
    elif alg == "HS512":
        digest = hashlib.sha512
    else:
        raise ValueError("unsupported_alg")
    return hmac.new(secret.encode("utf-8"), data, digest).digest()


def _encode_jwt(payload: dict, secret: str, alg: str = "HS256") -> str:
    header = {"alg": alg, "typ": "JWT"}
    header_b64 = _b64url(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    payload_b64 = _b64url(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = _b64url(_sign(alg, secret, signing_input))
    return f"{header_b64}.{payload_b64}.{signature}"


def test_decode_jwt_valid_hs256() -> None:
    payload = {
        "sub": "user-123",
        "role": "admin",
        "tenant_id": "acme",
        "permissions": ["run", "read"],
        "exp": int(time.time()) + 60,
    }
    token = _encode_jwt(payload, "secret")
    claims = decode_jwt(token, JwtConfig(secret="secret"))
    assert claims.subject == "user-123"
    assert claims.role == "admin"
    assert claims.tenant_id == "acme"
    assert "run" in claims.permissions
    assert claims.verified is True


def test_decode_jwt_invalid_signature() -> None:
    payload = {"sub": "user-123", "exp": int(time.time()) + 60}
    token = _encode_jwt(payload, "secret")
    with pytest.raises(JwtValidationError):
        decode_jwt(token, JwtConfig(secret="wrong"))


def test_decode_jwt_expired() -> None:
    payload = {"sub": "user-123", "exp": int(time.time()) - 10}
    token = _encode_jwt(payload, "secret")
    with pytest.raises(JwtValidationError):
        decode_jwt(token, JwtConfig(secret="secret", clock_skew_seconds=0))


def test_decode_jwt_allow_unverified() -> None:
    payload = {"sub": "user-123", "exp": int(time.time()) + 60}
    token = _encode_jwt(payload, "secret")
    claims = decode_jwt(
        token,
        JwtConfig(secret=None, allow_unverified=True),
    )
    assert claims.subject == "user-123"
    assert claims.verified is False

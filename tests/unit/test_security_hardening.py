import os
import pytest
from unittest.mock import MagicMock, patch, ANY
from skillos.attachments import _validate_attachment_limits, AttachmentError
from skillos.jwt_auth import _resolve_allow_unverified
from skillos.rate_limit import BackendRateLimiter, RateLimitConfig, rate_limiter_from_env

def test_attachment_limits():
    # Content type allowed
    _validate_attachment_limits("application/json", 100)
    
    # Content type disallowed
    with pytest.raises(AttachmentError, match="invalid_attachment_type"):
        _validate_attachment_limits("application/x-dosexec", 100)
        
    # Size limit
    with patch("skillos.attachments._env_int", return_value=50):
        with pytest.raises(AttachmentError, match="attachment_too_large"):
            _validate_attachment_limits("application/json", 100)

def test_jwt_strict_mode():
    # Not prod, requested True -> True
    env = {"SKILLOS_ENV": "dev", "SKILLOS_JWT_ALLOW_UNVERIFIED": "true"}
    assert _resolve_allow_unverified(env) is True
    
    # Prod, requested True -> False (Strict enforced)
    env = {"SKILLOS_ENV": "prod", "SKILLOS_JWT_ALLOW_UNVERIFIED": "true"}
    assert _resolve_allow_unverified(env) is False
    
    # Prod, requested False -> False
    env = {"SKILLOS_ENV": "prod", "SKILLOS_JWT_ALLOW_UNVERIFIED": "false"}
    assert _resolve_allow_unverified(env) is False

def test_rate_limiter_logic():
    backend = MagicMock()
    # Mock cache get returning None (empty) then "1"
    backend.get.side_effect = [None, "1", "2"]
    
    config = RateLimitConfig(enabled=True, limit=2, window_seconds=60)
    limiter = BackendRateLimiter(backend, config)
    
    # First call: current=0, cost=1 => 1. Allowed.
    assert limiter.check_and_consume("key") is True
    backend.set.assert_called_with(ANY, "1", 60)
    
    # Second call: current=1, cost=1 => 2. Allowed.
    assert limiter.check_and_consume("key") is True
    backend.set.assert_called_with(ANY, "2", 60)
    
    # Third call: current=2, cost=1 => 3. > Limit (2). Denied.
    assert limiter.check_and_consume("key") is False


def test_rate_limiter_strict_requires_redis(monkeypatch):
    monkeypatch.setenv("SKILLOS_RATE_LIMIT_STRICT", "1")
    monkeypatch.setenv("SKILLOS_RATE_LIMIT_ENABLED", "1")
    monkeypatch.delenv("SKILLOS_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(RuntimeError, match="rate_limit_strict_requires_redis"):
        rate_limiter_from_env()

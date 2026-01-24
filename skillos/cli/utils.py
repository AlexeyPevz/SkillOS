from __future__ import annotations
from pathlib import Path
import click

try:
    from skillos.jwt_auth import jwt_token_from_env, decode_jwt, jwt_config_from_env, JwtValidationError, JwtClaims
except ImportError:
    # Handle cases where dependencies might not be logically loaded yet, though unlikely in running app
    pass

def _emit_warnings(warnings: list[dict[str, object]] | None) -> None:
    if not warnings:
        return
    for warning in warnings:
        message = warning.get("message") or warning.get("code") or "warning"
        click.echo(f"warning: {message}", err=True)

def _blocked_message(reason: str) -> str:
    budget_reasons = {
        "per_request_limit_exceeded",
        "daily_limit_exceeded",
        "monthly_limit_exceeded",
    }
    if reason in budget_reasons:
        return f"budget_exceeded: {reason}"
    return reason

def _approval_message(policy_id: str) -> str:
    if policy_id == "approval_denied":
        return "approval_denied"
    if policy_id == "approval_token_invalid":
        return "approval_token_invalid"
    return "approval_required"

def _resolve_auth_context(jwt_token: str | None) -> JwtClaims | None:
    # Importing here to potentially avoid circular imports if jwt_auth depends on something unusual
    # But standard imports are generally preferred now if no cycles. 
    # For safety against cycles/heavy load if jwt_auth is heavy:
    from skillos.jwt_auth import jwt_token_from_env, decode_jwt, jwt_config_from_env, JwtValidationError

    token = jwt_token or jwt_token_from_env()
    if not token:
        return None
    try:
        return decode_jwt(token, jwt_config_from_env())
    except JwtValidationError as exc:
        raise click.ClickException(f"jwt_invalid: {exc}") from exc

def _apply_auth_context(
    root_path: Path,
    role: str | None,
    jwt_token: str | None,
) -> tuple[Path, str | None, dict[str, object] | None]:
    from skillos.tenancy import tenant_id_from_path, resolve_tenant_root

    context = _resolve_auth_context(jwt_token)
    if context is None:
        return root_path, role, None
    root_tenant = tenant_id_from_path(root_path)
    if context.tenant_id and root_tenant and root_tenant != context.tenant_id:
        raise click.ClickException("tenant_mismatch")
    resolved_root = root_path
    if context.tenant_id and not root_tenant:
        resolved_root = resolve_tenant_root(root_path, tenant_id=context.tenant_id)
    resolved_role = role or context.role
    return resolved_root, resolved_role, context.attributes

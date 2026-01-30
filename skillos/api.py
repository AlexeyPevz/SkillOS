from __future__ import annotations

import asyncio
from pathlib import Path
import inspect
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from skillos.jwt_auth import JwtValidationError, decode_jwt, jwt_config_from_env
from skillos.orchestrator import Orchestrator
from skillos.tenancy import resolve_tenant_root, tenant_id_from_path
from skillos.connectors import resolve_skills_root
from skillos.skills.deprecation import deprecate_skill, undeprecate_skill
from skillos.skills.errors import SkillValidationError
from skillos.skills.validation import validate_skills


def _ensure_httpx_testclient_compat() -> None:
    """Patch httpx.Client for starlette TestClient compatibility when needed."""
    try:
        import httpx
    except Exception:
        return

    try:
        signature = inspect.signature(httpx.Client.__init__)
    except (TypeError, ValueError):
        return
    if "app" in signature.parameters:
        return

    original_init = httpx.Client.__init__

    def patched_init(self, *args, app=None, **kwargs):  # type: ignore[no-untyped-def]
        return original_init(self, *args, **kwargs)

    httpx.Client.__init__ = patched_init  # type: ignore[assignment]


_ensure_httpx_testclient_compat()


app = FastAPI(title="SkillOS API", version="0.1.0")


class RunRequest(BaseModel):
    query: str = Field(..., min_length=1)
    execute: bool = False
    dry_run: bool = False
    approval: str | None = None
    approval_token: str | None = None
    role: str | None = None
    tags: list[str] | None = None
    mode: str | None = None
    session_id: str | None = None


class ValidateRequest(BaseModel):
    check_entrypoints: bool = True


class ValidateIssue(BaseModel):
    path: str
    category: str
    message: str
    skill_id: str | None = None


class ValidateResponse(BaseModel):
    status: str
    issues: list[ValidateIssue]


class DeprecateRequest(BaseModel):
    reason: str | None = None
    replacement_id: str | None = None


class SkillStatusResponse(BaseModel):
    status: str
    skill_id: str
    deprecated: bool


class RunResponse(BaseModel):
    status: str
    skill_id: str | None = None
    output: Any | None = None
    preview: dict[str, object] | None = None
    steps: list[str] | None = None
    alternatives: list[str] | None = None
    reason: str | None = None
    plan_id: str | None = None
    plan_path: str | None = None
    policy_id: str | None = None
    warnings: list[dict[str, object]] | None = None
    session_id: str | None = None


class EvalCaseResponse(BaseModel):
    input: str
    expected: str | None = None
    match: str
    passed: bool
    output: str
    details: str | None = None


class EvalResponse(BaseModel):
    skill_id: str
    total: int
    passed: int
    success_rate: float
    pass_threshold: float
    ok: bool
    cases: list[EvalCaseResponse]
    eval_path: str | None = None


def _subject_from_attributes(attributes: dict[str, object] | None) -> str | None:
    if not attributes:
        return None
    subject = attributes.get("subject")
    if subject is None:
        return None
    return str(subject).strip() or None


@app.get("/health")
def health(response: Response) -> dict[str, object]:
    from skillos.health import check_health
    report = check_health(resolve_skills_root())
    
    if report.status == "unhealthy":
        response.status_code = 503
    
    return {
        "status": report.status,
        "components": {
            k: {"status": v.status, "details": v.details, "latency_ms": v.latency_ms}
            for k, v in report.components.items()
        }
    }


@app.post("/run", response_model=RunResponse)
async def run_query(
    request: RunRequest,
    authorization: str | None = Header(default=None),
) -> RunResponse:
    root_path = resolve_skills_root()
    root_path, role, attributes = _resolve_auth_context(
        root_path,
        authorization=authorization,
        role=request.role,
    )
    subject = _subject_from_attributes(attributes)

    if request.session_id and subject:
        from skillos.session.store import SessionStore
        store = SessionStore(root_path)
        session = store.get_session(request.session_id)
        if session and session.user_id != subject:
            raise HTTPException(status_code=403, detail="session_forbidden")

    orchestrator = get_cached_orchestrator(Path(root_path))
    try:
        result = await orchestrator.run_query_async(
            query=request.query,
            execute=request.execute,
            dry_run=request.dry_run,
            approval=request.approval,
            approval_token=request.approval_token,
            role=role,
            attributes=attributes,
            tags=request.tags,
            mode=request.mode,
            session_id=request.session_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    preview = result.get("preview")
    if preview is not None:
        if hasattr(preview, "to_dict"):
            result["preview"] = preview.to_dict()
        elif isinstance(preview, dict):
            result["preview"] = preview
        else:
            result["preview"] = {"value": str(preview)}

    if result.get("plan_path") is not None:
        result["plan_path"] = str(result["plan_path"])

    return RunResponse(**result)


@app.post("/sessions", response_model=dict[str, str])
async def create_session(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    root_path = resolve_skills_root()
    root_path, _, attributes = _resolve_auth_context(
        root_path,
        authorization=authorization,
        role=None,
    )
    subject = _subject_from_attributes(attributes)
    
    from skillos.session.store import SessionStore
    store = SessionStore(root_path)
    session = store.create_session(user_id=subject)
    return {"session_id": session.id}


@app.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    root_path = resolve_skills_root()
    root_path, _, attributes = _resolve_auth_context(
        root_path,
        authorization=authorization,
        role=None,
    )
    subject = _subject_from_attributes(attributes)
    
    from skillos.session.store import SessionStore
    store = SessionStore(root_path)
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session_not_found")
    if session.user_id:
        if not subject or session.user_id != subject:
            raise HTTPException(status_code=403, detail="session_forbidden")
    elif subject:
        raise HTTPException(status_code=403, detail="session_forbidden")
    
    return {
        "session_id": session.id,
        "messages": [m.dict() for m in session.messages],
        "context": session.context
    }


# --- Orchestrator Caching ---
_ORCHESTRATOR_CACHE: dict[Path, Orchestrator] = {}

def get_cached_orchestrator(root_path: Path) -> Orchestrator:
    if root_path not in _ORCHESTRATOR_CACHE:
        # Initialize only if not present
        _ORCHESTRATOR_CACHE[root_path] = Orchestrator(root_path)
    return _ORCHESTRATOR_CACHE[root_path]



@app.post("/validate", response_model=ValidateResponse)
async def validate_endpoint(
    request: ValidateRequest,
    authorization: str | None = Header(default=None),
) -> ValidateResponse:
    root_path = resolve_skills_root()
    root_path, _, _ = _resolve_auth_context(
        root_path,
        authorization=authorization,
        role=None,
    )
    issues = await asyncio.to_thread(
        validate_skills,
        Path(root_path),
        check_entrypoints=request.check_entrypoints,
    )
    status = "ok" if not issues else "invalid"
    return ValidateResponse(
        status=status,
        issues=[
            ValidateIssue(
                path=str(issue.path),
                category=issue.category,
                message=issue.message,
                skill_id=issue.skill_id,
            )
            for issue in issues
        ],
    )


@app.post("/skills/{skill_id:path}/deprecate", response_model=SkillStatusResponse)
async def deprecate_skill_endpoint(
    skill_id: str,
    request: DeprecateRequest,
    authorization: str | None = Header(default=None),
) -> SkillStatusResponse:
    root_path = resolve_skills_root()
    root_path, _, _ = _resolve_auth_context(
        root_path,
        authorization=authorization,
        role=None,
    )
    try:
        await asyncio.to_thread(
            deprecate_skill,
            Path(root_path),
            skill_id,
            reason=request.reason,
            replacement_id=request.replacement_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SkillValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillStatusResponse(
        status="deprecated",
        skill_id=skill_id,
        deprecated=True,
    )


@app.post("/skills/{skill_id:path}/undeprecate", response_model=SkillStatusResponse)
async def undeprecate_skill_endpoint(
    skill_id: str,
    authorization: str | None = Header(default=None),
) -> SkillStatusResponse:
    root_path = resolve_skills_root()
    root_path, _, _ = _resolve_auth_context(
        root_path,
        authorization=authorization,
        role=None,
    )
    try:
        await asyncio.to_thread(undeprecate_skill, Path(root_path), skill_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SkillValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillStatusResponse(
        status="undeprecated",
        skill_id=skill_id,
        deprecated=False,
    )


@app.post("/skills/{skill_id:path}/eval", response_model=EvalResponse)
async def eval_skill_endpoint(
    skill_id: str,
    authorization: str | None = Header(default=None),
    save: bool = False,
) -> EvalResponse:
    root_path = resolve_skills_root()
    root_path, _, _ = _resolve_auth_context(
        root_path,
        authorization=authorization,
        role=None,
    )
    try:
        from skillos.skills.eval import run_skill_eval, save_eval_result, SkillEvalError

        result = await asyncio.to_thread(run_skill_eval, skill_id, Path(root_path))
    except SkillEvalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    eval_path = None
    if save:
        eval_path = str(
            await asyncio.to_thread(save_eval_result, result, Path(root_path))
        )

    return EvalResponse(
        skill_id=result.skill_id,
        total=result.total,
        passed=result.passed,
        success_rate=result.success_rate,
        pass_threshold=result.pass_threshold,
        ok=result.ok,
        cases=[
            EvalCaseResponse(
                input=case.input,
                expected=case.expected,
                match=case.match,
                passed=case.passed,
                output=case.output,
                details=case.details,
            )
            for case in result.cases
        ],
        eval_path=eval_path,
    )


def _extract_bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.lower().startswith("bearer "):
        return raw[7:].strip() or None
    return raw


def _resolve_auth_context(
    root_path: Path,
    *,
    authorization: str | None,
    role: str | None,
) -> tuple[Path, str | None, dict[str, object] | None]:
    jwt_token = _extract_bearer_token(authorization)
    attributes: dict[str, object] | None = None
    if jwt_token:
        try:
            claims = decode_jwt(jwt_token, jwt_config_from_env())
        except JwtValidationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        root_tenant = tenant_id_from_path(root_path)
        if claims.tenant_id and root_tenant and root_tenant != claims.tenant_id:
            raise HTTPException(status_code=403, detail="tenant_mismatch")
        if claims.tenant_id and not root_tenant:
            root_path = resolve_tenant_root(root_path, tenant_id=claims.tenant_id)
        role = role or claims.role
        attributes = claims.attributes
    return Path(root_path), role, attributes

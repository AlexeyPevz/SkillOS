from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import inspect
import json
import os
from pathlib import Path
import time
from typing import Iterable

import yaml

from skillos.approval_gate import ApprovalDecision, ApprovalGate
from skillos.authorization import PermissionChecker, default_permissions_path
from skillos.budget import (
    BudgetManager,
    budget_config_from_env,
    budget_usage_store_from_env,
)
from skillos.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerStore,
    circuit_breaker_config_from_env,
    default_circuit_breaker_path,
)
from skillos.policy_engine import ApprovalRequirement, PolicyEngine, default_policy_path
from skillos.risk_scorer import RiskScorer
from skillos.skills.models import SkillMetadata
from skillos.skills.registry import resolve_entrypoint
from skillos.storage import atomic_write_text
from skillos.telemetry import EventLogger, default_log_path, new_request_id
from skillos.tenancy import resolve_tenant_root
from skillos.tool_wrapper import ToolWrapper


COMPOSITION_ENTRYPOINT = "skillos.composition:run_composed_skill"
DEFAULT_PARALLEL_LIMIT = 4

StepGroup = list[str]
StepInput = str | list[str] | tuple[str, ...]


class CompositionError(ValueError):
    """Raised when a composition definition is invalid."""


class CompositionBlocked(CompositionError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CompositionSpec:
    skill_id: str
    steps: list[StepGroup]
    version: str
    active: bool = False


@dataclass(frozen=True)
class CompositionActivationResult:
    skill_id: str
    activated: bool
    approval: ApprovalDecision
    status: str


class CompositionStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def exists(self, skill_id: str) -> bool:
        return self.path_for(skill_id).exists()

    def load(self, skill_id: str) -> CompositionSpec | None:
        path = self.path_for(skill_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise CompositionError("Composition file must be a mapping")
        steps = raw.get("steps")
        if not isinstance(steps, list):
            raise CompositionError(
                "Composition steps must be a list of skill ids or parallel groups"
            )
        normalized_steps = _normalize_step_groups(steps)
        version = str(raw.get("version", "0.1.0"))
        active = bool(raw.get("active", False))
        return CompositionSpec(
            skill_id=skill_id,
            steps=normalized_steps,
            version=version,
            active=active,
        )

    def save(self, spec: CompositionSpec) -> None:
        path = self.path_for(spec.skill_id)
        payload = {
            "id": spec.skill_id,
            "steps": _serialize_step_groups(spec.steps),
            "version": spec.version,
            "active": spec.active,
        }
        atomic_write_text(
            path,
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def path_for(self, skill_id: str) -> Path:
        domain, name = _parse_skill_id(skill_id)
        return self._root / "compositions" / domain / f"{name}.json"


class CompositionEngine:
    def __init__(
        self,
        registry,
        store: CompositionStore | None = None,
        *,
        parallel_limit: int | None = None,
    ) -> None:
        self._registry = registry
        self._store = store or CompositionStore(registry.root)
        self._parallel_limit = parallel_limit or parallel_limit_from_env()
        self._budget_manager = BudgetManager(
            budget_usage_store_from_env(self._registry.root),
            budget_config_from_env(),
        )
        self._permission_checker = PermissionChecker.from_path(
            default_permissions_path(self._registry.root)
        )
        policy_engine = PolicyEngine.from_path(default_policy_path(self._registry.root))
        self._tool_wrapper = ToolWrapper(
            risk_scorer=RiskScorer(),
            policy_engine=policy_engine,
            approval_gate=ApprovalGate(
                required_token=os.getenv("SKILLOS_APPROVAL_TOKEN")
            ),
        )
        self._circuit_breaker = CircuitBreaker(
            CircuitBreakerStore(default_circuit_breaker_path(self._registry.root)),
            circuit_breaker_config_from_env(),
        )

    def execute(
        self,
        skill_id: str,
        payload: str,
        *,
        allow_inactive: bool = False,
        _stack: list[str] | None = None,
        logger: EventLogger | None = None,
        role: str | None = None,
        attributes: dict[str, object] | None = None,
        approval_status: str | None = None,
        approval_token: str | None = None,
        charge_budget: bool = True,
    ) -> object:
        stack = list(_stack or [])
        if skill_id in stack:
            raise CompositionError("Composition cycle detected")
        spec = self._store.load(skill_id)
        if not spec:
            return self._registry._execute_entrypoint(skill_id, payload=payload)
        if not spec.active and not allow_inactive:
            raise PermissionError(f"Composed skill {skill_id} is not active")
        stack.append(skill_id)
        logger = logger or EventLogger(
            default_log_path(self._registry.root), request_id=new_request_id()
        )
        result: object = payload
        order_index = 0
        for group_index, group in enumerate(spec.steps):
            group_payload = str(result)
            if len(group) == 1:
                result = self._execute_step(
                    skill_id,
                    group[0],
                    group_payload,
                    allow_inactive=allow_inactive,
                    stack=stack,
                    logger=logger,
                    order_index=order_index,
                    group_index=group_index,
                    role=role,
                    attributes=attributes,
                    approval_status=approval_status,
                    approval_token=approval_token,
                    charge_budget=charge_budget,
                )
            else:
                result = self._execute_parallel_group(
                    skill_id,
                    group,
                    group_payload,
                    allow_inactive=allow_inactive,
                    stack=stack,
                    logger=logger,
                    order_index=order_index,
                    group_index=group_index,
                    role=role,
                    attributes=attributes,
                    approval_status=approval_status,
                    approval_token=approval_token,
                    charge_budget=charge_budget,
                )
            order_index += len(group)
        return result

    def _execute_step(
        self,
        composed_skill_id: str,
        step_id: str,
        payload: str,
        *,
        allow_inactive: bool,
        stack: list[str],
        logger: EventLogger,
        order_index: int,
        group_index: int,
        role: str | None,
        attributes: dict[str, object] | None,
        approval_status: str | None,
        approval_token: str | None,
        charge_budget: bool,
    ) -> object:
        start = time.perf_counter()
        try:
            self._authorize_step(
                step_id,
                payload,
                role=role,
                attributes=attributes,
                approval_status=approval_status,
                approval_token=approval_token,
                charge_budget=charge_budget,
            )
            output = self.execute(
                step_id,
                payload=payload,
                allow_inactive=allow_inactive,
                _stack=stack,
                logger=logger,
                role=role,
                attributes=attributes,
                approval_status=approval_status,
                approval_token=approval_token,
                charge_budget=charge_budget,
            )
        except CompositionBlocked as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            _log_composition_step(
                logger,
                composed_skill_id,
                step_id,
                order_index,
                group_index,
                duration_ms,
                status="blocked",
                error_class=exc.reason,
            )
            raise
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            _log_composition_step(
                logger,
                composed_skill_id,
                step_id,
                order_index,
                group_index,
                duration_ms,
                status="error",
                error_class=exc.__class__.__name__,
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        _log_composition_step(
            logger,
            composed_skill_id,
            step_id,
            order_index,
            group_index,
            duration_ms,
            status="success",
        )
        return output

    def _execute_parallel_group(
        self,
        composed_skill_id: str,
        group: list[str],
        payload: str,
        *,
        allow_inactive: bool,
        stack: list[str],
        logger: EventLogger,
        order_index: int,
        group_index: int,
        role: str | None,
        attributes: dict[str, object] | None,
        approval_status: str | None,
        approval_token: str | None,
        charge_budget: bool,
    ) -> str:
        missing = object()
        outputs: list[object] = [missing for _ in group]
        durations: list[float | None] = [None for _ in group]
        for step_id in group:
            self._authorize_step(
                step_id,
                payload,
                role=role,
                attributes=attributes,
                approval_status=approval_status,
                approval_token=approval_token,
                charge_budget=charge_budget,
            )
        with ThreadPoolExecutor(max_workers=self._parallel_limit) as executor:
            future_map = {}
            for index, step_id in enumerate(group):
                future = executor.submit(
                    self._execute_with_timing,
                    step_id,
                    payload,
                    allow_inactive,
                    stack,
                    logger,
                    durations,
                    index,
                    role,
                    attributes,
                    approval_status,
                    approval_token,
                    charge_budget,
                )
                future_map[future] = (index, step_id)

            for future in as_completed(future_map):
                index, step_id = future_map[future]
                try:
                    output = future.result()
                except Exception as exc:
                    duration_ms = durations[index] or 0.0
                    _log_composition_step(
                        logger,
                        composed_skill_id,
                        step_id,
                        order_index + index,
                        group_index,
                        duration_ms,
                        status="error",
                        error_class=exc.__class__.__name__,
                    )
                    for pending in future_map:
                        if pending is not future:
                            pending.cancel()
                    raise
                duration_ms = durations[index] or 0.0
                outputs[index] = output
                _log_composition_step(
                    logger,
                    composed_skill_id,
                    step_id,
                    order_index + index,
                    group_index,
                    duration_ms,
                    status="success",
                )
        return "\n".join(str(output) for output in outputs if output is not missing)

    def _execute_with_timing(
        self,
        step_id: str,
        payload: str,
        allow_inactive: bool,
        stack: list[str],
        logger: EventLogger,
        durations: list[float | None],
        index: int,
        role: str | None,
        attributes: dict[str, object] | None,
        approval_status: str | None,
        approval_token: str | None,
        charge_budget: bool,
    ) -> object:
        start = time.perf_counter()
        try:
            return self.execute(
                step_id,
                payload=payload,
                allow_inactive=allow_inactive,
                _stack=stack,
                logger=logger,
                role=role,
                attributes=attributes,
                approval_status=approval_status,
                approval_token=approval_token,
                charge_budget=charge_budget,
            )
        finally:
            durations[index] = (time.perf_counter() - start) * 1000

    def _authorize_step(
        self,
        step_id: str,
        payload: str,
        *,
        role: str | None,
        attributes: dict[str, object] | None,
        approval_status: str | None,
        approval_token: str | None,
        charge_budget: bool,
    ) -> None:
        metadata = self._registry.get(step_id)
        skill_tags = metadata.tags if metadata else None
        perm_decision = self._permission_checker.authorize(
            step_id,
            role,
            skill_tags=skill_tags,
            attributes=attributes,
        )
        if not perm_decision.allowed:
            raise CompositionBlocked(perm_decision.policy_id or "permission_denied")

        approval_decision = self._tool_wrapper.authorize(
            step_id,
            payload,
            approval_status=approval_status,
            approval_token=approval_token,
        )
        if not approval_decision.approval.allowed:
            raise CompositionBlocked(
                approval_decision.approval.policy_id or "approval_required"
            )

        circuit_decision = self._circuit_breaker.allow(step_id)
        if not circuit_decision.allowed:
            raise CompositionBlocked(circuit_decision.reason or "circuit_breaker_open")

        budget_result = (
            self._budget_manager.authorize()
            if charge_budget
            else self._budget_manager.evaluate()
        )
        if not budget_result.allowed:
            raise CompositionBlocked(budget_result.reason or "budget_block")


def compose_skill(
    root: Path,
    skill_id: str,
    steps: Iterable[StepInput],
    *,
    name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> CompositionSpec:
    root_path = Path(root)
    normalized_steps = _normalize_step_groups(steps)
    store = CompositionStore(root_path)
    _validate_no_cycles(skill_id, normalized_steps, store)

    from skillos.skills.registry import SkillRegistry

    registry = SkillRegistry(root_path)
    registry.load_all()
    _validate_steps_exist(normalized_steps, registry, store)
    _validate_io_contracts(normalized_steps, registry, store)

    existing = store.load(skill_id)
    metadata_path = _metadata_path(root_path, skill_id)
    if metadata_path.exists() and not existing:
        raise CompositionError("Skill already exists")
    version = _next_version(existing.version) if existing else "0.1.0"
    spec = CompositionSpec(
        skill_id=skill_id,
        steps=normalized_steps,
        version=version,
        active=False,
    )
    store.save(spec)

    _write_metadata(
        metadata_path,
        skill_id,
        name=name,
        description=description,
        tags=tags,
        version=version,
    )
    return spec


def execute_composed_skill(
    skill_id: str,
    registry,
    payload: str,
    *,
    allow_inactive: bool = False,
) -> object:
    engine = CompositionEngine(registry)
    return engine.execute(skill_id, payload, allow_inactive=allow_inactive)


def activate_composed_skill(
    root: Path,
    skill_id: str,
    *,
    approval_status: str | None = None,
    approval_token: str | None = None,
    required_token: str | None = None,
    require_tests: bool = True,
) -> CompositionActivationResult:
    root_path = Path(root)
    store = CompositionStore(root_path)
    spec = store.load(skill_id)
    if not spec:
        raise CompositionError(f"Unknown composed skill: {skill_id}")
    if require_tests and not _coverage_path(root_path, skill_id).exists():
        approval = ApprovalDecision(
            allowed=False,
            policy_id="tests_required",
            status="tests_required",
        )
        return CompositionActivationResult(
            skill_id=skill_id,
            activated=False,
            approval=approval,
            status="tests_required",
        )
    requirement = ApprovalRequirement(
        required=True,
        policy_id="composition_activation",
        reasons=["composition_activation"],
        risk_score=0,
        risk_level="low",
    )
    gate = ApprovalGate(required_token=required_token)
    approval = gate.check(requirement, approval_status, approval_token)
    if not approval.allowed:
        return CompositionActivationResult(
            skill_id=skill_id,
            activated=False,
            approval=approval,
            status=approval.status,
        )
    activated = CompositionSpec(
        skill_id=spec.skill_id,
        steps=spec.steps,
        version=spec.version,
        active=True,
    )
    store.save(activated)
    return CompositionActivationResult(
        skill_id=skill_id,
        activated=True,
        approval=approval,
        status="activated",
    )


def run_composed_skill(payload: str = "ok") -> str:
    raise RuntimeError("Composed skills must be executed via SkillRegistry")


def _metadata_path(root: Path, skill_id: str) -> Path:
    domain, name = _parse_skill_id(skill_id)
    return Path(root) / "metadata" / domain / f"{name}.yaml"


def _write_metadata(
    path: Path,
    skill_id: str,
    *,
    name: str | None,
    description: str | None,
    tags: list[str] | None,
    version: str,
) -> None:
    domain, name_part = _parse_skill_id(skill_id)
    tags = tags or [domain, "composed"]
    metadata = SkillMetadata(
        id=skill_id,
        name=name or name_part.replace("_", " ").title(),
        description=description or f"Composed skill for {skill_id}",
        version=version,
        entrypoint=COMPOSITION_ENTRYPOINT,
        tags=tags,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(metadata.model_dump(), sort_keys=False),
        encoding="utf-8",
    )


def _coverage_path(root: Path, skill_id: str) -> Path:
    root_path = resolve_tenant_root(root)
    safe_id = skill_id.replace("/", "_")
    return Path(root_path) / "coverage" / f"{safe_id}.json"


def _validate_steps_exist(steps, registry, store: CompositionStore) -> None:
    missing = [
        step
        for step in _iter_step_ids(steps)
        if not store.exists(step) and registry.get(step) is None
    ]
    if missing:
        raise CompositionError(f"Unknown skills: {', '.join(missing)}")


def _validate_io_contracts(steps, registry, store: CompositionStore) -> None:
    for step in _iter_step_ids(steps):
        if store.exists(step):
            continue
        metadata = registry.get(step)
        if not metadata:
            raise CompositionError(f"Unknown skill: {step}")
        func = resolve_entrypoint(metadata.entrypoint, registry.root)
        _validate_signature(step, func)


def _validate_signature(skill_id: str, func) -> None:
    signature = inspect.signature(func)
    params = list(signature.parameters.values())
    if any(param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD) for param in params):
        return
    required_positional = [
        param
        for param in params
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
        and param.default is param.empty
    ]
    required_keyword = [
        param
        for param in params
        if param.kind is param.KEYWORD_ONLY and param.default is param.empty
    ]
    if required_keyword:
        if (
            len(required_keyword) == 1
            and required_keyword[0].name == "payload"
            and not required_positional
        ):
            return
        raise CompositionError(f"Invalid IO contract for {skill_id}")
    if len(required_positional) > 1:
        raise CompositionError(f"Invalid IO contract for {skill_id}")


def _validate_no_cycles(
    skill_id: str, steps: list[StepGroup], store: CompositionStore
) -> None:
    flat_steps = list(_iter_step_ids(steps))
    if skill_id in flat_steps:
        raise CompositionError("Composition cycle detected")
    visiting: list[str] = []

    def walk(node: str) -> None:
        if node in visiting:
            raise CompositionError("Composition cycle detected")
        spec = store.load(node)
        if not spec:
            return
        visiting.append(node)
        for step in _iter_step_ids(spec.steps):
            if step == skill_id:
                raise CompositionError("Composition cycle detected")
            walk(step)
        visiting.pop()

    for step in flat_steps:
        walk(step)


def parallel_limit_from_env() -> int:
    raw_value = os.getenv("SKILLOS_PARALLEL_LIMIT", str(DEFAULT_PARALLEL_LIMIT))
    try:
        limit = int(raw_value)
    except ValueError:
        return DEFAULT_PARALLEL_LIMIT
    return max(1, limit)


def _normalize_step_groups(steps: Iterable[StepInput]) -> list[StepGroup]:
    normalized: list[StepGroup] = []
    for step in steps:
        if isinstance(step, str):
            cleaned = step.strip()
            if not cleaned:
                raise CompositionError(
                    "Composition steps must be a list of skill ids or parallel groups"
                )
            normalized.append([cleaned])
            continue
        if not isinstance(step, (list, tuple)):
            raise CompositionError(
                "Composition steps must be a list of skill ids or parallel groups"
            )
        group: list[str] = []
        for entry in step:
            if not isinstance(entry, str):
                raise CompositionError(
                    "Composition steps must be a list of skill ids or parallel groups"
                )
            cleaned = entry.strip()
            if not cleaned:
                raise CompositionError(
                    "Composition steps must be a list of skill ids or parallel groups"
                )
            group.append(cleaned)
        if not group:
            raise CompositionError("Composition requires at least one step")
        normalized.append(group)
    if not normalized:
        raise CompositionError("Composition requires at least one step")
    return normalized


def _serialize_step_groups(steps: list[StepGroup]) -> list[object]:
    if all(len(group) == 1 for group in steps):
        return [group[0] for group in steps]
    payload: list[object] = []
    for group in steps:
        if len(group) == 1:
            payload.append(group[0])
        else:
            payload.append(group)
    return payload


def _iter_step_ids(steps: Iterable[StepGroup]) -> Iterable[str]:
    for group in steps:
        for step in group:
            yield step


def _log_composition_step(
    logger: EventLogger,
    composed_skill_id: str,
    step_id: str,
    order_index: int,
    group_index: int,
    duration_ms: float,
    *,
    status: str,
    error_class: str | None = None,
) -> None:
    payload = {
        "status": status,
        "skill_id": composed_skill_id,
        "step_id": step_id,
        "duration_ms": duration_ms,
        "order": order_index,
        "group": group_index,
    }
    if error_class:
        payload["error_class"] = error_class
    logger.log("composition_step", **payload)


def _next_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return "0.1.0"
    major, minor, patch = (int(part) for part in parts)
    return f"{major}.{minor}.{patch + 1}"


def _parse_skill_id(skill_id: str) -> tuple[str, str]:
    if "/" not in skill_id or skill_id.startswith("/") or skill_id.endswith("/"):
        raise CompositionError("Skill id must be in 'domain/name' format")
    domain, name = skill_id.split("/", 1)
    if not domain or not name:
        raise CompositionError("Skill id must be in 'domain/name' format")
    return domain, name

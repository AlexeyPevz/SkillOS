from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Iterable

from skillos.approval_gate import ApprovalGate, approval_token_from_env
from skillos.authorization import PermissionChecker, default_permissions_path
from skillos.budget import (
    BudgetManager,
    budget_config_from_env,
    budget_usage_store_from_env,
)
from skillos.composition import parallel_limit_from_env
from skillos.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerStore,
    circuit_breaker_config_from_env,
    default_circuit_breaker_path,
)
from skillos.debugging import StepController
from skillos.skills.deprecation import build_deprecation_warning
from skillos.policy_engine import PolicyEngine, default_policy_path
from skillos.risk_scorer import RiskScorer
from skillos.routing import to_internal_id, to_public_id
from skillos.skills.registry import SkillRegistry
from skillos.telemetry import EventLogger, default_log_path, new_request_id
from skillos.tool_wrapper import ToolWrapper


class PipelineError(ValueError):
    pass


StepGroup = list[str]
StepInput = str | list[str] | tuple[str, ...]


@dataclass(frozen=True)
class PipelineStepResult:
    step_id: str
    status: str
    output: str | None
    duration_ms: float
    order: int
    group: int
    error_class: str | None = None


@dataclass(frozen=True)
class PipelineResult:
    status: str
    output: str | None
    steps: list[PipelineStepResult]
    reason: str | None = None
    warnings: list[dict[str, object]] = field(default_factory=list)


def normalize_pipeline_steps(steps: Iterable[StepInput]) -> list[StepGroup]:
    normalized: list[StepGroup] = []
    for step in steps:
        if isinstance(step, str):
            cleaned = step.strip()
            if not cleaned:
                raise PipelineError("pipeline_steps_required")
            if "|" in cleaned:
                parts = [part.strip() for part in cleaned.split("|") if part.strip()]
                if not parts:
                    raise PipelineError("pipeline_steps_required")
                normalized.append([to_internal_id(part) for part in parts])
            else:
                normalized.append([to_internal_id(cleaned)])
            continue
        if not isinstance(step, (list, tuple)):
            raise PipelineError("pipeline_steps_required")
        if not step:
            raise PipelineError("pipeline_steps_required")
        group: list[str] = []
        for entry in step:
            if not isinstance(entry, str):
                raise PipelineError("pipeline_steps_required")
            cleaned = entry.strip()
            if not cleaned:
                raise PipelineError("pipeline_steps_required")
            group.append(to_internal_id(cleaned))
        normalized.append(group)
    if not normalized:
        raise PipelineError("pipeline_steps_required")
    return normalized


class PipelineRunner:
    def __init__(
        self,
        root_path: Path,
        *,
        log_path: Path | None = None,
        registry: SkillRegistry | None = None,
        budget_manager: BudgetManager | None = None,
        permission_checker: PermissionChecker | None = None,
        tool_wrapper: ToolWrapper | None = None,
        parallel_limit: int | None = None,
        step_controller: StepController | None = None,
    ) -> None:
        self.root_path = Path(root_path)
        self.log_path = log_path or default_log_path(self.root_path)
        self.registry = registry or SkillRegistry(self.root_path)
        if registry is None:
            self.registry.load_all()

        self.budget_manager = budget_manager or BudgetManager(
            budget_usage_store_from_env(self.root_path),
            budget_config_from_env(),
        )
        self.permission_checker = permission_checker or PermissionChecker.from_path(
            default_permissions_path(self.root_path)
        )
        policy_engine = PolicyEngine.from_path(default_policy_path(self.root_path))
        self.tool_wrapper = tool_wrapper or ToolWrapper(
            risk_scorer=RiskScorer(),
            policy_engine=policy_engine,
            approval_gate=ApprovalGate(required_token=approval_token_from_env()),
        )
        self.circuit_breaker = CircuitBreaker(
            CircuitBreakerStore(default_circuit_breaker_path(self.root_path)),
            circuit_breaker_config_from_env(),
        )
        self.parallel_limit = parallel_limit or parallel_limit_from_env()
        self.step_controller = step_controller

    def run(
        self,
        steps: Iterable[StepInput],
        *,
        payload: str = "ok",
        approval_status: str | None = None,
        approval_token: str | None = None,
        role: str | None = None,
        attributes: dict[str, object] | None = None,
        request_id: str | None = None,
        session_context: dict[str, object] | None = None,
    ) -> PipelineResult:
        self._maybe_reload_registry()
        normalized_steps = normalize_pipeline_steps(steps)
        request_id = request_id or new_request_id()
        logger = EventLogger(self.log_path, request_id=request_id)

        current_payload = payload
        step_results: list[PipelineStepResult] = []
        warnings: list[dict[str, object]] = []
        order_index = 0
        for group_index, group in enumerate(normalized_steps):
            if len(group) == 1:
                step_id = group[0]
                public_id = to_public_id(step_id)
                block = self._authorize_step(
                    logger,
                    step_id,
                    public_id,
                    current_payload,
                    role,
                    attributes,
                    approval_status,
                    approval_token,
                    order_index,
                    group_index,
                    warnings,
                )
                if block:
                    step_results.append(block)
                    return PipelineResult(
                        status=block.status,
                        output=None,
                        steps=step_results,
                        reason=block.error_class,
                        warnings=warnings,
                    )
                step_result = self._execute_step(
                    logger,
                    step_id,
                    public_id,
                    current_payload,
                    order_index,
                    group_index,
                    role=role,
                    attributes=attributes,
                    approval_status=approval_status,
                    approval_token=approval_token,
                    session_context=session_context,
                )
                step_results.append(step_result)
                if step_result.status != "success":
                    return PipelineResult(
                        status=step_result.status,
                        output=None,
                        steps=step_results,
                        reason=step_result.error_class,
                        warnings=warnings,
                    )
                current_payload = step_result.output or ""
            else:
                group_result = self._execute_parallel_group(
                    logger,
                    group,
                    current_payload,
                    role,
                    attributes,
                    approval_status,
                    approval_token,
                    order_index,
                    group_index,
                    warnings,
                    session_context=session_context,
                )
                step_results.extend(group_result.steps)
                if group_result.status != "success":
                    return PipelineResult(
                        status=group_result.status,
                        output=None,
                        steps=step_results,
                        reason=group_result.reason,
                        warnings=warnings,
                    )
                current_payload = group_result.output or ""
            order_index += len(group)

        return PipelineResult(
            status="success",
            output=current_payload,
            steps=step_results,
            reason=None,
            warnings=warnings,
        )

    async def run_async(
        self,
        steps: Iterable[StepInput],
        *,
        payload: str = "ok",
        approval_status: str | None = None,
        approval_token: str | None = None,
        role: str | None = None,
        attributes: dict[str, object] | None = None,
        request_id: str | None = None,
        session_context: dict[str, object] | None = None,
    ) -> PipelineResult:
        self._maybe_reload_registry()
        normalized_steps = normalize_pipeline_steps(steps)
        request_id = request_id or new_request_id()
        logger = EventLogger(self.log_path, request_id=request_id)

        current_payload = payload
        step_results: list[PipelineStepResult] = []
        warnings: list[dict[str, object]] = []
        order_index = 0
        
        try:
            for group_index, group in enumerate(normalized_steps):
                if len(group) == 1:
                    step_id = group[0]
                    public_id = to_public_id(step_id)
                    block = self._authorize_step(
                        logger,
                        step_id,
                        public_id,
                        current_payload,
                        role,
                        attributes,
                        approval_status,
                        approval_token,
                        order_index,
                        group_index,
                        warnings,
                    )
                    if block:
                        step_results.append(block)
                        return PipelineResult(
                            status=block.status,
                            output=None,
                            steps=step_results,
                            reason=block.error_class,
                            warnings=warnings,
                        )
                    
                    step_result = await self._execute_step_async(
                        logger,
                        step_id,
                        public_id,
                        current_payload,
                        order_index,
                        group_index,
                        role=role,
                        attributes=attributes,
                        approval_status=approval_status,
                        approval_token=approval_token,
                        session_context=session_context,
                    )
                    step_results.append(step_result)
                    if step_result.status != "success":
                        return PipelineResult(
                            status=step_result.status,
                            output=None,
                            steps=step_results,
                            reason=step_result.error_class,
                            warnings=warnings,
                        )
                    current_payload = step_result.output or ""
                else:
                    group_result = await self._execute_parallel_group_async(
                        logger,
                        group,
                        current_payload,
                        role,
                        attributes,
                        approval_status,
                        approval_token,
                        order_index,
                        group_index,
                        warnings,
                        session_context=session_context,
                    )
                    step_results.extend(group_result.steps)
                    if group_result.status != "success":
                        return PipelineResult(
                            status=group_result.status,
                            output=None,
                            steps=step_results,
                            reason=group_result.reason,
                            warnings=warnings,
                        )
                    current_payload = group_result.output or ""
                order_index += len(group)
        except asyncio.CancelledError:
            logger.log("pipeline_cancelled", request_id=request_id)
            # Resources are cleaned up by individual step cancellation handlers if needed
            raise

        return PipelineResult(
            status="success",
            output=current_payload,
            steps=step_results,
            reason=None,
            warnings=warnings,
        )

    def _authorize_step(
        self,
        logger: EventLogger,
        internal_id: str,
        public_id: str,
        payload: str,
        role: str | None,
        attributes: dict[str, object] | None,
        approval_status: str | None,
        approval_token: str | None,
        order_index: int,
        group_index: int,
        warnings: list[dict[str, object]],
    ) -> PipelineStepResult | None:
        start = time.perf_counter()
        metadata = self.registry.get(internal_id)
        self._warn_deprecated(metadata, public_id, warnings, logger=logger)

        permission_decision = self._permission_check(
            internal_id,
            role,
            attributes,
            metadata,
            logger=logger,
        )
        if not permission_decision.allowed:
            return self._blocked_step(
                logger,
                public_id,
                order_index,
                group_index,
                start,
                payload,
                permission_decision.policy_id,
            )

        decision = self._approval_check(
            internal_id,
            payload,
            approval_status,
            approval_token,
            logger=logger,
        )
        if not decision.approval.allowed:
            return self._blocked_step(
                logger,
                public_id,
                order_index,
                group_index,
                start,
                payload,
                decision.approval.policy_id,
            )

        allowed, reason = self._circuit_check(internal_id, logger=logger)
        if not allowed:
            return self._blocked_step(
                logger,
                public_id,
                order_index,
                group_index,
                start,
                payload,
                reason or "circuit_breaker_open",
            )

        budget_result = self._budget_check(logger=logger)
        if not budget_result.allowed:
            logger.log(
                "policy_decision",
                allowed=False,
                policy_id="budget_block",
            )
            return self._blocked_step(
                logger,
                public_id,
                order_index,
                group_index,
                start,
                payload,
                budget_result.reason or "budget_block",
            )
        return None

    def _blocked_step(
        self,
        logger: EventLogger,
        step_id: str,
        order_index: int,
        group_index: int,
        start: float,
        payload: str,
        reason: str,
    ) -> PipelineStepResult:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.log(
            "execution_result",
            status="blocked",
            duration_ms=duration_ms,
            error_class=reason,
            skill_id=step_id,
        )
        result = PipelineStepResult(
            step_id=step_id,
            status="blocked",
            output=None,
            duration_ms=duration_ms,
            order=order_index,
            group=group_index,
            error_class=reason,
        )
        self._log_pipeline_step(logger, result)
        self._pause_step(
            step_id,
            inputs={"payload": payload},
            outputs={"status": "blocked", "reason": reason},
            duration_ms=duration_ms,
        )
        return result

    def _execute_step(
        self,
        logger: EventLogger,
        internal_id: str,
        public_id: str,
        payload: str,
        order_index: int,
        group_index: int,
        *,
        role: str | None,
        attributes: dict[str, object] | None,
        approval_status: str | None,
        approval_token: str | None,
        pause: bool = True,
        session_context: dict[str, object] | None = None,
    ) -> PipelineStepResult:
        start = time.perf_counter()
        try:
            output = self.registry.execute(
                internal_id,
                payload=payload,
                role=role,
                attributes=attributes,
                approval_status=approval_status,
                approval_token=approval_token,
                session_context=session_context,
                charge_budget=False,
            )
        except Exception as exc:
            import traceback
            print(f"DEBUG: EXECUTION ERROR for {internal_id}: {exc}")
            traceback.print_exc()
            duration_ms = (time.perf_counter() - start) * 1000
            logger.log(
                "execution_result",
                status="error",
                duration_ms=duration_ms,
                error_class=exc.__class__.__name__,
                skill_id=public_id,
            )
            self.circuit_breaker.record_failure(internal_id)
            result = PipelineStepResult(
                step_id=public_id,
                status="error",
                output=None,
                duration_ms=duration_ms,
                order=order_index,
                group=group_index,
                error_class=exc.__class__.__name__,
            )
            self._log_pipeline_step(logger, result)
            if pause:
                self._pause_step(
                    public_id,
                    inputs={"payload": payload},
                    outputs={
                        "status": "error",
                        "error_class": exc.__class__.__name__,
                    },
                    duration_ms=duration_ms,
                )
            return result

        duration_ms = (time.perf_counter() - start) * 1000
        logger.log(
            "execution_result",
            status="success",
            duration_ms=duration_ms,
            skill_id=public_id,
        )
        self.circuit_breaker.record_success(internal_id)
        result = PipelineStepResult(
            step_id=public_id,
            status="success",
            output=str(output),
            duration_ms=duration_ms,
            order=order_index,
            group=group_index,
        )
        self._log_pipeline_step(logger, result)
        if pause:
            self._pause_step(
                public_id,
                inputs={"payload": payload},
                outputs={"status": "success", "output": str(output)},
                duration_ms=duration_ms,
            )
        return result

    async def _execute_step_async(
        self,
        logger: EventLogger,
        internal_id: str,
        public_id: str,
        payload: str,
        order_index: int,
        group_index: int,
        *,
        role: str | None,
        attributes: dict[str, object] | None,
        approval_status: str | None,
        approval_token: str | None,
        pause: bool = True,
        session_context: dict[str, object] | None = None,
    ) -> PipelineStepResult:
        start = time.perf_counter()
        try:
            output = await self.registry.execute_async(
                internal_id,
                payload=payload,
                role=role,
                attributes=attributes,
                approval_status=approval_status,
                approval_token=approval_token,
                session_context=session_context,
                charge_budget=False,
            )
        except asyncio.CancelledError:
            # Re-raise to let the runner handle it
            raise
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.log(
                "execution_result",
                status="error",
                duration_ms=duration_ms,
                error_class=exc.__class__.__name__,
                skill_id=public_id,
            )
            self.circuit_breaker.record_failure(internal_id)
            result = PipelineStepResult(
                step_id=public_id,
                status="error",
                output=None,
                duration_ms=duration_ms,
                order=order_index,
                group=group_index,
                error_class=exc.__class__.__name__,
            )
            self._log_pipeline_step(logger, result)
            if pause:
                self._pause_step(
                    public_id,
                    inputs={"payload": payload},
                    outputs={
                        "status": "error",
                        "error_class": exc.__class__.__name__,
                    },
                    duration_ms=duration_ms,
                )
            return result

        duration_ms = (time.perf_counter() - start) * 1000
        logger.log(
            "execution_result",
            status="success",
            duration_ms=duration_ms,
            skill_id=public_id,
        )
        self.circuit_breaker.record_success(internal_id)
        result = PipelineStepResult(
            step_id=public_id,
            status="success",
            output=str(output),
            duration_ms=duration_ms,
            order=order_index,
            group=group_index,
        )
        self._log_pipeline_step(logger, result)
        if pause:
            self._pause_step(
                public_id,
                inputs={"payload": payload},
                outputs={"status": "success", "output": str(output)},
                duration_ms=duration_ms,
            )
        return result

    def _execute_parallel_group(
        self,
        logger: EventLogger,
        group: list[str],
        payload: str,
        role: str | None,
        attributes: dict[str, object] | None,
        approval_status: str | None,
        approval_token: str | None,
        order_index: int,
        group_index: int,
        warnings: list[dict[str, object]],
        session_context: dict[str, object] | None = None,
    ) -> PipelineResult:
        step_results: list[PipelineStepResult] = []
        public_ids = [to_public_id(step_id) for step_id in group]

        for offset, (internal_id, public_id) in enumerate(zip(group, public_ids)):
            block = self._authorize_step(
                logger,
                internal_id,
                public_id,
                payload,
                role,
                attributes,
                approval_status,
                approval_token,
                order_index + offset,
                group_index,
                warnings,
            )
            if block:
                step_results.append(block)
                return PipelineResult(
                    status=block.status,
                    output=None,
                    steps=step_results,
                    reason=block.error_class,
                )

        outputs: list[str | None] = [None for _ in group]
        results: list[PipelineStepResult | None] = [None for _ in group]
        with ThreadPoolExecutor(max_workers=self.parallel_limit) as executor:
            future_map = {}
            for offset, (internal_id, public_id) in enumerate(zip(group, public_ids)):
                future = executor.submit(
                    self._execute_step,
                    logger,
                    internal_id,
                    public_id,
                    payload,
                    order_index + offset,
                    group_index,
                    role=role,
                    attributes=attributes,
                    approval_status=approval_status,
                    approval_token=approval_token,
                    pause=False,
                    session_context=session_context,
                )
                future_map[future] = offset
            for future in as_completed(future_map):
                index = future_map[future]
                result = future.result()
                results[index] = result
                outputs[index] = result.output
                if result.status != "success":
                    for pending in future_map:
                        if pending is not future:
                            pending.cancel()
                    step_results.extend(result for result in results if result)
                    self._pause_parallel_group(payload, results)
                    return PipelineResult(
                        status=result.status,
                        output=None,
                        steps=step_results,
                        reason=result.error_class,
                    )

        step_results.extend(result for result in results if result)
        self._pause_parallel_group(payload, results)
        combined = "\n".join(
            output for output in outputs if output is not None
        )
        return PipelineResult(
            status="success",
            output=combined,
            steps=step_results,
            reason=None,
        )

    async def _execute_parallel_group_async(
        self,
        logger: EventLogger,
        group: list[str],
        payload: str,
        role: str | None,
        attributes: dict[str, object] | None,
        approval_status: str | None,
        approval_token: str | None,
        order_index: int,
        group_index: int,
        warnings: list[dict[str, object]],
        session_context: dict[str, object] | None = None,
    ) -> PipelineResult:
        step_results: list[PipelineStepResult] = []
        public_ids = [to_public_id(step_id) for step_id in group]

        # Auth check remains sync as it's quick metadata/policy check
        for offset, (internal_id, public_id) in enumerate(zip(group, public_ids)):
            block = self._authorize_step(
                logger,
                internal_id,
                public_id,
                payload,
                role,
                attributes,
                approval_status,
                approval_token,
                order_index + offset,
                group_index,
                warnings,
            )
            if block:
                step_results.append(block)
                return PipelineResult(
                    status=block.status,
                    output=None,
                    steps=step_results,
                    reason=block.error_class,
                )

        task_map: dict[asyncio.Task[PipelineStepResult], int] = {}
        for offset, (internal_id, public_id) in enumerate(zip(group, public_ids)):
            task = asyncio.create_task(
                self._execute_step_async(
                    logger,
                    internal_id,
                    public_id,
                    payload,
                    order_index + offset,
                    group_index,
                    role=role,
                    attributes=attributes,
                    approval_status=approval_status,
                    approval_token=approval_token,
                    pause=False,
                    session_context=session_context,
                )
            )
            task_map[task] = offset

        results: list[PipelineStepResult | None] = [None for _ in group]
        outputs: list[str | None] = [None for _ in group]

        pending: set[asyncio.Task[PipelineStepResult]] = set(task_map.keys())
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                index = task_map[task]
                try:
                    res = task.result()
                except asyncio.CancelledError:
                    continue
                except Exception as exc:
                    res = PipelineStepResult(
                        step_id=public_ids[index],
                        status="error",
                        output=None,
                        duration_ms=0.0,
                        order=order_index + index,
                        group=group_index,
                        error_class=exc.__class__.__name__,
                    )
                    self._log_pipeline_step(logger, res)
                results[index] = res
                outputs[index] = res.output
                if res.status != "success":
                    for pending_task in pending:
                        pending_task.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    step_results.extend([r for r in results if r])
                    self._pause_parallel_group(payload, results)
                    return PipelineResult(
                        status=res.status,
                        output=None,
                        steps=step_results,
                        reason=res.error_class,
                    )

        step_results.extend([r for r in results if r])
        self._pause_parallel_group(payload, results)
        combined = "\n".join(output for output in outputs if output is not None)
        return PipelineResult(
            status="success",
            output=combined,
            steps=step_results,
            reason=None,
        )

    def _circuit_check(
        self,
        internal_id: str,
        *,
        logger: EventLogger,
    ) -> tuple[bool, str | None]:
        circuit_decision = self.circuit_breaker.allow(internal_id)
        if circuit_decision.allowed:
            return True, None
        logger.log(
            "policy_decision",
            allowed=False,
            policy_id="circuit_breaker_open",
        )
        return False, circuit_decision.reason or "circuit_breaker_open"

    def _budget_check(self, *, logger: EventLogger):
        budget_result = self.budget_manager.authorize()
        logger.log(
            "budget_check",
            allowed=budget_result.allowed,
            reason=budget_result.reason,
            model=budget_result.model,
            estimated_cost=budget_result.estimated_cost,
            remaining_daily=budget_result.remaining_daily,
            remaining_monthly=budget_result.remaining_monthly,
        )
        return budget_result

    @staticmethod
    def _warn_deprecated(
        metadata,
        public_id: str,
        warnings: list[dict[str, object]],
        *,
        logger: EventLogger,
    ) -> None:
        if not metadata or not metadata.deprecated:
            return
        warnings.append(build_deprecation_warning(public_id, metadata))
        logger.log(
            "deprecated_skill_used",
            skill_id=public_id,
            deprecation_reason=metadata.deprecation_reason,
            replacement_id=metadata.replacement_id,
        )

    def _permission_check(
        self,
        internal_id: str,
        role: str | None,
        attributes: dict[str, object] | None,
        metadata,
        *,
        logger: EventLogger,
    ):
        skill_tags = metadata.tags if metadata else None
        permission_decision = self.permission_checker.authorize(
            internal_id,
            role,
            skill_tags=skill_tags,
            attributes=attributes,
        )
        logger.log(
            "permission_decision",
            allowed=permission_decision.allowed,
            policy_id=permission_decision.policy_id,
            role=permission_decision.role,
            skill_id=permission_decision.skill_id,
            required_permissions=permission_decision.required_permissions,
            missing_permissions=permission_decision.missing_permissions,
        )
        return permission_decision

    def _approval_check(
        self,
        internal_id: str,
        payload: str,
        approval_status: str | None,
        approval_token: str | None,
        *,
        logger: EventLogger,
    ):
        decision = self.tool_wrapper.authorize(
            internal_id,
            payload,
            approval_status=approval_status,
            approval_token=approval_token,
        )
        logger.log(
            "policy_decision",
            allowed=decision.approval.allowed,
            policy_id=decision.approval.policy_id,
            approval_required=decision.requirement.required,
            approval_reason=decision.requirement.policy_id,
            risk_score=decision.risk.score,
            risk_level=decision.risk.level,
            approval_status=decision.approval.status,
        )
        return decision

    @staticmethod
    def _log_pipeline_step(logger: EventLogger, result: PipelineStepResult) -> None:
        payload = {
            "status": result.status,
            "step_id": result.step_id,
            "duration_ms": result.duration_ms,
            "order": result.order,
            "group": result.group,
        }
        if result.error_class:
            payload["error_class"] = result.error_class
        logger.log("pipeline_step", **payload)

    def _pause_step(
        self,
        step_id: str,
        *,
        inputs: dict[str, object] | None,
        outputs: dict[str, object] | None,
        duration_ms: float | None,
    ) -> None:
        if not self.step_controller:
            return
        self.step_controller.pause(
            step_id,
            inputs=inputs,
            outputs=outputs,
            duration_ms=duration_ms,
        )

    def _pause_parallel_group(
        self,
        payload: str,
        results: list[PipelineStepResult | None],
    ) -> None:
        if not self.step_controller:
            return
        for result in results:
            if not result:
                continue
            outputs = {"status": result.status}
            if result.error_class:
                outputs["error_class"] = result.error_class
            if result.output is not None:
                outputs["output"] = result.output
            self._pause_step(
                result.step_id,
                inputs={"payload": payload},
                outputs=outputs,
                duration_ms=result.duration_ms,
            )

    def _maybe_reload_registry(self) -> None:
        self.registry.reload_if_changed()

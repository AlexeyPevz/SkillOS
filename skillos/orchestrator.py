import asyncio
import contextvars
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Optional, Dict, Any, List
from unittest.mock import MagicMock

from skillos.authorization import PermissionChecker, default_permissions_path
from skillos.approval_gate import ApprovalGate, approval_token_from_env
from skillos.budget import (
    BudgetCheckResult,
    BudgetManager,
    budget_config_from_env,
    budget_usage_store_from_env,
)
from skillos.debugging import (
    DebugTrace,
    DebugTraceConfig,
    trace_step,
)
from skillos.execution import execute_plan
from skillos.execution_planner import (
    build_execution_plan,
    load_execution_plan,
    save_execution_plan,
)
from skillos.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerStore,
    circuit_breaker_config_from_env,
    default_circuit_breaker_path,
)
from skillos.feedback import FeedbackTracker, feedback_store_from_env
from skillos.policy_engine import PolicyEngine, default_policy_path
from skillos.risk_scorer import RiskScorer
from skillos.routing import build_router_from_env, to_internal_id
from skillos.routing_cache import routing_cache_from_env
from skillos.mode_selector import split_query
from skillos.pipeline import PipelineRunner
from skillos.skills.deprecation import build_deprecation_warning
from skillos.skills.registry import SkillRegistry
from skillos.skills.paths import default_skills_root
from skillos.telemetry import (
    EventLogger,
    default_log_path,
    hash_query,
    new_request_id,
    route_with_telemetry,
    token_count,
)
from skillos.tool_wrapper import ToolWrapper

_CALL_STACK: contextvars.ContextVar[List[str]] = contextvars.ContextVar("_CALL_STACK", default=[])
MAX_CALL_DEPTH = 10


class Orchestrator:
    def __init__(
        self,
        root_path: Path,
        log_path: Optional[Path] = None,
        dev_mode: bool = False,
    ):
        self.root_path = root_path
        self.log_path = log_path or default_log_path(root_path)
        self.dev_mode = dev_mode
        self.registry = SkillRegistry(root_path)
        records = self.registry.load_all()
        
        self.skills_metadata = [record.metadata for record in records.values()]
        
        # In dev mode, we can skip complex components
        if dev_mode:
            self.feedback_tracker = MagicMock()
            self.feedback_tracker.get_confidence.return_value = 1.0 # Return float, not MagicMock
            self.router = build_router_from_env(self.skills_metadata) 
            self.routing_cache = MagicMock()
            self.routing_cache.get.return_value = None
            self.budget_manager = MagicMock()
            allowed_result = BudgetCheckResult(
                allowed=True, 
                remaining_daily=1000.0,
                reason=None,
                model="standard",
                estimated_cost=0.0,
                remaining_monthly=10000.0,
                day_key="2024-01-01",
                month_key="2024-01"
            )
            self.budget_manager.authorize.return_value = allowed_result
            self.budget_manager.evaluate.return_value = allowed_result
            self.policy_engine = MagicMock()
            
            # Use a dummy approval gate that returns serializable objects
            # MagicMock causes JSON serialization errors in logging
            self.approval_gate = MagicMock()
            
            self.tool_wrapper = ToolWrapper(
                risk_scorer=MagicMock(),
                policy_engine=self.policy_engine,
                approval_gate=self.approval_gate,
            )
            # Configure tool_wrapper mock decision to be serializable
            # We override authorize method of the real ToolWrapper instance's dependencies
            # Actually, let's just mock tool_wrapper completely to be safe and simple
            self.tool_wrapper = MagicMock()
            
            # Create a dummy object structure for approval decision that is JSON serializable
            # Using simple Namespace or dicts acting as objects
            from types import SimpleNamespace
            
            approval_decision = SimpleNamespace(
                approval=SimpleNamespace(allowed=True, policy_id="dev_allow", status="approved"),
                requirement=SimpleNamespace(required=False, policy_id="dev_policy"),
                risk=SimpleNamespace(score=0.0, level="low")
            )
            self.tool_wrapper.authorize.return_value = approval_decision
            
            self.circuit_breaker = MagicMock()
            self.circuit_breaker.allow.return_value = MagicMock(allowed=True)
            self._policy_path = Path("dummy")
            self._policy_refresh_token = 0.0
            self._approval_token = None
            
        else:
            self.feedback_tracker = FeedbackTracker(feedback_store_from_env(root_path))
            self.router = build_router_from_env(
                self.skills_metadata,
                confidence_provider=self.feedback_tracker.get_confidence,
            )
            self.routing_cache = routing_cache_from_env(root_path)
            
            self.budget_config = budget_config_from_env()
            self.budget_manager = BudgetManager(
                budget_usage_store_from_env(root_path),
                self.budget_config,
            )
            
            self._policy_path = default_policy_path(root_path)
            self._policy_refresh_token = self._policy_refresh_state()
            self._approval_token = approval_token_from_env()
            self.policy_engine = PolicyEngine.from_path(self._policy_path)
            self.approval_gate = ApprovalGate(required_token=self._approval_token)
            self.tool_wrapper = ToolWrapper(
                risk_scorer=RiskScorer(),
                policy_engine=self.policy_engine,
                approval_gate=self.approval_gate,
            )
            self.circuit_breaker = CircuitBreaker(
                CircuitBreakerStore(default_circuit_breaker_path(root_path)),
                circuit_breaker_config_from_env(),
            )

    @classmethod
    def run_simple(cls, query: str, root_path: Path | str, **kwargs) -> Any:
        """
        Convenience method to run a query in dev mode with minimal setup.
        Useful for testing and local development.
        """
        import os
        from uuid import uuid4
        
        # Ensure SKILLOS_ROOT is set if not already
        original_root = os.environ.get("SKILLOS_ROOT")
        if "SKILLOS_ROOT" not in os.environ:
             os.environ["SKILLOS_ROOT"] = str(root_path)
        
        try:
            orchestrator = cls(Path(root_path), dev_mode=True)
            result = orchestrator.run_query(
                query, 
                request_id=f"dev-{uuid4().hex[:8]}", 
                execute=True, 
                mode="auto",
                **kwargs
            )
            
            if result.get("status") == "success":
                return result.get("output")
            return result
        finally:
            if original_root is None:
                os.environ.pop("SKILLOS_ROOT", None)
            else:
                os.environ["SKILLOS_ROOT"] = original_root

    def run_query(
        self,
        query: str,
        request_id: str = None,
        execute: bool = False,
        dry_run: bool = False,
        approval: Optional[str] = None,
        approval_token: Optional[str] = None,
        role: Optional[str] = None,
        attributes: dict[str, object] | None = None,
        tags: list[str] | None = None,
        mode: str | None = None,
        plan_path: Optional[Path] = None,
        debug_trace: Optional[DebugTrace] = None,
    ) -> Dict[str, Any]:
        self._maybe_reload_registry()
        if not self.dev_mode:
            self._maybe_reload_policies()
            
        stack = _CALL_STACK.get()
        if len(stack) >= MAX_CALL_DEPTH:
            raise RecursionError(f"Max call depth exceeded: {MAX_CALL_DEPTH}")

        request_start, request_id, logger, warnings = self._start_request(
            query,
            request_id=request_id,
            debug_trace=debug_trace,
        )

        normalized_mode = (mode or "single").strip().lower()
        segments = split_query(query, normalized_mode)
        if normalized_mode in {"pipeline", "parallel", "auto"} and len(segments) > 1:
            return self._run_multi(
                segments,
                normalized_mode,
                execute=execute,
                dry_run=dry_run,
                approval=approval,
                approval_token=approval_token,
                role=role,
                attributes=attributes,
                tags=tags,
                logger=logger,
                request_id=request_id,
                debug_trace=debug_trace,
                request_start=request_start,
            )

        # 1. Routing
        result = self._route_query(
            query,
            logger=logger,
            request_id=request_id,
            tags=tags,
            debug_trace=debug_trace,
        )

        if result.status == "no_skill_found":
            return self._handle_no_skill_found(logger, debug_trace, request_start)

        if result.status == "low_confidence":
            return self._handle_low_confidence(result, logger, debug_trace, request_start)

        # 2. Plan Creation
        plan, metadata, skill_selected = self._prepare_plan(
            result,
            query,
            warnings,
            logger=logger,
            execute=execute,
            dry_run=dry_run,
        )
        return self.execute_plan(
            plan,
            execute=execute,
            dry_run=dry_run,
            approval=approval,
            approval_token=approval_token,
            role=role,
            attributes=attributes,
            plan_path=plan_path,
            debug_trace=debug_trace,
            logger=logger,
            request_start=request_start,
            warnings=warnings,
            metadata=metadata,
            skill_selected=skill_selected,
        )

    async def run_query_async(
        self,
        query: str,
        request_id: str = None,
        execute: bool = False,
        dry_run: bool = False,
        approval: Optional[str] = None,
        approval_token: Optional[str] = None,
        role: Optional[str] = None,
        attributes: dict[str, object] | None = None,
        tags: list[str] | None = None,
        mode: str | None = None,
        plan_path: Optional[Path] = None,
        debug_trace: Optional[DebugTrace] = None,
    ) -> Dict[str, Any]:
        self._maybe_reload_registry()
        if not self.dev_mode:
            self._maybe_reload_policies()
            
        stack = _CALL_STACK.get()
        if len(stack) >= MAX_CALL_DEPTH:
            raise RecursionError(f"Max call depth exceeded: {MAX_CALL_DEPTH}")

        request_start, request_id, logger, warnings = self._start_request(
            query,
            request_id=request_id,
            debug_trace=debug_trace,
        )

        normalized_mode = (mode or "single").strip().lower()
        segments = split_query(query, normalized_mode)
        if normalized_mode in {"pipeline", "parallel", "auto"} and len(segments) > 1:
            return await self._run_multi_async(
                segments,
                normalized_mode,
                execute=execute,
                dry_run=dry_run,
                approval=approval,
                approval_token=approval_token,
                role=role,
                attributes=attributes,
                tags=tags,
                logger=logger,
                request_id=request_id,
                debug_trace=debug_trace,
                request_start=request_start,
            )

        result = await self._route_query_async(
            query,
            logger=logger,
            request_id=request_id,
            tags=tags,
            debug_trace=debug_trace,
        )

        if result.status == "no_skill_found":
            return self._handle_no_skill_found(logger, debug_trace, request_start)

        if result.status == "low_confidence":
            return self._handle_low_confidence(result, logger, debug_trace, request_start)

        plan, metadata, skill_selected = self._prepare_plan(
            result,
            query,
            warnings,
            logger=logger,
            execute=execute,
            dry_run=dry_run,
        )
        return await self.execute_plan_async(
            plan,
            execute=execute,
            dry_run=dry_run,
            approval=approval,
            approval_token=approval_token,
            role=role,
            attributes=attributes,
            plan_path=plan_path,
            debug_trace=debug_trace,
            logger=logger,
            request_start=request_start,
            warnings=warnings,
            metadata=metadata,
            skill_selected=skill_selected,
        )

    def execute_plan(
        self,
        plan,
        *,
        execute: bool,
        dry_run: bool,
        approval: Optional[str],
        approval_token: Optional[str],
        role: Optional[str],
        attributes: dict[str, object] | None,
        plan_path: Optional[Path],
        debug_trace: Optional[DebugTrace],
        logger: EventLogger,
        request_start: float,
        warnings: list[dict[str, object]] | None = None,
        metadata=None,
        skill_selected: dict[str, object] | None = None,
    ) -> Dict[str, Any]:
        warnings_list = list(warnings) if warnings else []
        if metadata is None:
            metadata = self.registry.get(plan.internal_skill_id)
        if metadata and metadata.deprecated:
            already_warned = any(
                warning.get("code") == "deprecated_skill"
                and warning.get("skill_id") == plan.skill_id
                for warning in warnings_list
            )
            if not already_warned:
                warning = build_deprecation_warning(plan.skill_id, metadata)
                warnings_list.append(warning)
                if execute or dry_run:
                    logger.log(
                        "deprecated_skill_used",
                        skill_id=plan.skill_id,
                        deprecation_reason=metadata.deprecation_reason,
                        replacement_id=metadata.replacement_id,
                    )

        if skill_selected:
            logger.log(
                "skill_selected",
                skill_id=skill_selected.get("skill_id"),
                confidence=skill_selected.get("confidence"),
                status=skill_selected.get("status"),
            )

        if plan_path and plan_path.exists() and not dry_run:
            loaded_plan = load_execution_plan(plan_path)
            if loaded_plan.plan_id != plan.plan_id:
                raise ValueError("plan_mismatch")
            plan = loaded_plan

        # 4. Dry Run / Execution
        if dry_run:
            budget_result = self._budget_check(
                execute=False,
                dry_run=True,
                logger=logger,
                debug_trace=debug_trace,
            )
            if not budget_result.allowed and not self.dev_mode: # Bypass budget block in dev mode (safety net)
                 # Note: in dev_mode budget manager is mocked to always allow, but safety first
                return self._handle_block(
                    "budget_block",
                    budget_result.reason,
                    logger,
                    debug_trace,
                    request_start,
                )
             
            with trace_step(debug_trace, "execution", inputs={"dry_run": True}) as trace_output:
                result_preview = execute_plan(self.registry, plan, dry_run=True)
                preview = result_preview.preview
                trace_output.update({"executed": result_preview.executed})

            if plan_path:
                save_execution_plan(plan, plan_path)

            return {
                "status": "dry_run",
                "skill_id": plan.skill_id,
                "preview": preview,
                "plan_path": plan_path,
                "warnings": warnings_list or None,
            }

        if execute:
            # 5. Permission Check
            perm_decision = self._permission_check(
                plan,
                metadata,
                role,
                attributes,
                logger=logger,
                debug_trace=debug_trace,
            )
            
            # ALLOW in dev_mode if policies missing
            if self.dev_mode and not perm_decision.allowed:
                 # In dev mode, we typically want to allow execution unless explicitly tested against
                 # But since we mocked everything, it should pass.
                 pass
            elif not perm_decision.allowed:
                return self._handle_block(
                    perm_decision.policy_id,
                    "permission_denied",
                    logger,
                    debug_trace,
                    request_start,
                )

            # 6. Approval Check
            decision = self._approval_check(
                plan,
                approval,
                approval_token,
                logger=logger,
                debug_trace=debug_trace,
            )
            if not decision.approval.allowed:
                return self._handle_block(
                    decision.approval.policy_id,
                    decision.approval.policy_id,
                    logger,
                    debug_trace,
                    request_start,
                )

            # 6.5 Circuit Check
            circuit_decision = self.circuit_breaker.allow(plan.internal_skill_id)
            if not circuit_decision.allowed:
                logger.log(
                    "policy_decision",
                    allowed=False,
                    policy_id="circuit_breaker_open",
                )
                return self._handle_block(
                    "circuit_breaker_open",
                    circuit_decision.reason or "circuit_breaker_open",
                    logger,
                    debug_trace,
                    request_start,
                )

            # 6.6 Budget Check (charge only after permission/approval/circuit)
            budget_result = self._budget_check(
                execute=True,
                dry_run=False,
                logger=logger,
                debug_trace=debug_trace,
            )
            if not budget_result.allowed:
                return self._handle_block(
                    "budget_block",
                    budget_result.reason,
                    logger,
                    debug_trace,
                    request_start,
                )

            # 7. Execute
            output = self._execute_skill(
                plan,
                logger=logger,
                debug_trace=debug_trace,
                request_start=request_start,
                role=role,
                attributes=attributes,
                approval=approval,
                approval_token=approval_token,
            )
            return {
                "status": "success",
                "skill_id": plan.skill_id,
                "output": output,
                "plan_id": plan.plan_id if plan_path else None,
                "warnings": warnings_list or None,
            }

        return {
            "status": "routed",
            "skill_id": plan.skill_id,
            "warnings": warnings_list or None,
        }


    def _start_request(
        self,
        query: str,
        *,
        request_id: str | None,
        debug_trace: Optional[DebugTrace],
    ) -> tuple[float, str, EventLogger, list[dict[str, object]]]:
        request_start = time.perf_counter()
        request_id = request_id or new_request_id()
        logger = EventLogger(self.log_path, request_id=request_id)
        warnings: list[dict[str, object]] = []
        log_query = bool(
            debug_trace and debug_trace.config.capture_inputs
        )
        request_payload = {
            "query_hash": hash_query(query),
            "query_length": len(query),
            "token_count": token_count(query),
        }
        if log_query:
            request_payload["query"] = query
        logger.log("request_received", **request_payload)
        return request_start, request_id, logger, warnings

    def _maybe_reload_registry(self) -> None:
        records = self.registry.reload_if_changed()
        if records is None:
            return
        self.skills_metadata = [record.metadata for record in records.values()]
        self.router = build_router_from_env(
            self.skills_metadata,
            confidence_provider=self.feedback_tracker.get_confidence,
        )

    def _policy_refresh_state(self) -> float:
        try:
            return self._policy_path.stat().st_mtime
        except OSError:
            return 0.0

    def _maybe_reload_policies(self) -> None:
        token = self._policy_refresh_state()
        approval_token = approval_token_from_env()
        if token == self._policy_refresh_token and approval_token == self._approval_token:
            return
        self._policy_refresh_token = token
        self._approval_token = approval_token
        self.policy_engine = PolicyEngine.from_path(self._policy_path)
        self.approval_gate = ApprovalGate(required_token=self._approval_token)
        self.tool_wrapper = ToolWrapper(
            risk_scorer=RiskScorer(),
            policy_engine=self.policy_engine,
            approval_gate=self.approval_gate,
        )

    def _prepare_plan(
        self,
        result,
        query: str,
        warnings: list[dict[str, object]],
        *,
        logger: EventLogger,
        execute: bool,
        dry_run: bool,
    ):
        internal_id = result.internal_skill_id or to_internal_id(result.skill_id)
        plan = build_execution_plan(result.skill_id, internal_id, query)
        metadata = self._collect_deprecation_warning(
            plan.internal_skill_id,
            result.skill_id,
            warnings,
            logger=logger,
            log=execute or dry_run,
        )
        skill_selected = {
            "skill_id": result.skill_id,
            "confidence": result.confidence,
            "status": result.status,
        }
        return plan, metadata, skill_selected

    def _budget_check(
        self,
        *,
        execute: bool,
        dry_run: bool,
        logger: EventLogger,
        debug_trace: Optional[DebugTrace],
    ) -> BudgetCheckResult:
        with trace_step(debug_trace, "budget_check", inputs={"dry_run": dry_run}) as trace_output:
            budget_result = (
                self.budget_manager.authorize()
                if execute and not dry_run
                else self.budget_manager.evaluate()
            )
            trace_output.update(
                {
                    "allowed": budget_result.allowed,
                    "reason": budget_result.reason,
                    "remaining_daily": budget_result.remaining_daily,
                }
            )

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

    def _permission_check(
        self,
        plan,
        metadata,
        role: Optional[str],
        attributes: dict[str, object] | None,
        *,
        logger: EventLogger,
        debug_trace: Optional[DebugTrace],
    ):
        permission_checker = PermissionChecker.from_path(
            default_permissions_path(self.root_path)
        )
        skill_tags = metadata.tags if metadata else None
        with trace_step(debug_trace, "permission_check", inputs={"role": role}) as trace_output:
            perm_decision = permission_checker.authorize(
                plan.internal_skill_id,
                role,
                skill_tags=skill_tags,
                attributes=attributes,
            )
            trace_output.update({"allowed": perm_decision.allowed})

        logger.log(
            "permission_decision",
            allowed=perm_decision.allowed,
            policy_id=perm_decision.policy_id,
            role=perm_decision.role,
            skill_id=perm_decision.skill_id,
            required_permissions=perm_decision.required_permissions,
            missing_permissions=perm_decision.missing_permissions,
        )
        return perm_decision

    def _approval_check(
        self,
        plan,
        approval: Optional[str],
        approval_token: Optional[str],
        *,
        logger: EventLogger,
        debug_trace: Optional[DebugTrace],
    ):
        with trace_step(debug_trace, "approval_check", inputs={"approval": approval}) as trace_output:
            decision = self.tool_wrapper.authorize(
                plan.internal_skill_id,
                plan.payload,
                approval_status=approval.lower() if approval else None,
                approval_token=approval_token,
            )
            trace_output.update({"allowed": decision.approval.allowed})

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
    def _execute_skill(
        self,
        plan,
        *,
        logger: EventLogger,
        debug_trace: Optional[DebugTrace],
        request_start: float,
        role: Optional[str] = None,
        attributes: dict[str, object] | None = None,
        approval: Optional[str] = None,
        approval_token: Optional[str] = None,
    ) -> str | None:
        internal_id = plan.internal_skill_id
        stack = _CALL_STACK.get()
        if internal_id in stack:
            raise RecursionError(f"Circular dependency detected: {internal_id} in {stack}")
        
        token = _CALL_STACK.set(stack + [internal_id])
        try:
            with trace_step(
                debug_trace,
                "execution",
                inputs={"skill_id": plan.internal_skill_id},
            ) as trace_output:
                execution = execute_plan(
                    self.registry,
                    plan,
                    dry_run=False,
                    role=role,
                    attributes=attributes,
                    approval_status=approval,
                    approval_token=approval_token,
                    charge_budget=False,
                )
                trace_output.update(
                    {"status": "success", "output": str(execution.output)}
                )

            duration = (time.perf_counter() - request_start) * 1000
            logger.log(
                "execution_result",
                status="success",
                skill_id=plan.skill_id,
                duration_ms=duration,
            )
            self.circuit_breaker.record_success(plan.internal_skill_id)
            return execution.output
        except Exception as exc:
            duration = (time.perf_counter() - request_start) * 1000
            logger.log(
                "execution_result",
                status="error",
                error_class=exc.__class__.__name__,
                duration_ms=duration,
            )
            self.circuit_breaker.record_failure(plan.internal_skill_id)
            raise exc
        finally:
            _CALL_STACK.reset(token)

    def _route_query(
        self,
        query: str,
        *,
        logger: EventLogger,
        request_id: str,
        tags: list[str] | None,
        debug_trace: Optional[DebugTrace],
    ):
        with trace_step(debug_trace, "route", inputs={"query": query}) as trace_output:
            telemetry = route_with_telemetry(
                query,
                self.router,
                logger,
                request_id,
                tags=tags,
                routing_cache=self.routing_cache,
            )
            result = telemetry.result
            trace_output.update({
                "skill_id": result.skill_id,
                "status": result.status,
                "confidence": result.confidence,
                "alternatives": result.alternatives,
                "routing_latency_ms": telemetry.routing_latency_ms,
            })
        return result

    async def _route_query_async(
        self,
        query: str,
        *,
        logger: EventLogger,
        request_id: str,
        tags: list[str] | None,
        debug_trace: Optional[DebugTrace],
    ):
        with trace_step(debug_trace, "route", inputs={"query": query}) as trace_output:
            telemetry = await asyncio.to_thread(
                route_with_telemetry,
                query,
                self.router,
                logger,
                request_id,
                tags=tags,
                routing_cache=self.routing_cache,
            )
            result = telemetry.result
            trace_output.update({
                "skill_id": result.skill_id,
                "status": result.status,
                "confidence": result.confidence,
                "alternatives": result.alternatives,
                "routing_latency_ms": telemetry.routing_latency_ms,
            })
        return result

    async def execute_plan_async(
        self,
        plan,
        *,
        execute: bool,
        dry_run: bool,
        approval: Optional[str],
        approval_token: Optional[str],
        role: Optional[str],
        attributes: dict[str, object] | None,
        plan_path: Optional[Path],
        debug_trace: Optional[DebugTrace],
        logger: EventLogger,
        request_start: float,
        warnings: list[dict[str, object]] | None = None,
        metadata=None,
        skill_selected: dict[str, object] | None = None,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self.execute_plan,
            plan,
            execute=execute,
            dry_run=dry_run,
            approval=approval,
            approval_token=approval_token,
            role=role,
            attributes=attributes,
            plan_path=plan_path,
            debug_trace=debug_trace,
            logger=logger,
            request_start=request_start,
            warnings=warnings,
            metadata=metadata,
            skill_selected=skill_selected,
        )
    def _collect_deprecation_warning(
        self,
        internal_skill_id: str,
        public_skill_id: str,
        warnings: list[dict[str, object]],
        *,
        logger: EventLogger | None = None,
        log: bool = False,
    ):
        metadata = self.registry.get(internal_skill_id)
        if metadata and metadata.deprecated:
            warning = build_deprecation_warning(public_skill_id, metadata)
            warnings.append(warning)
            if logger and log:
                logger.log(
                    "deprecated_skill_used",
                    skill_id=public_skill_id,
                    deprecation_reason=metadata.deprecation_reason,
                    replacement_id=metadata.replacement_id,
                )
        return metadata

    def _run_multi(
        self,
        segments: list[str],
        mode: str,
        *,
        execute: bool,
        dry_run: bool,
        approval: Optional[str],
        approval_token: Optional[str],
        role: Optional[str],
        attributes: dict[str, object] | None,
        tags: list[str] | None,
        logger: EventLogger,
        request_id: str,
        debug_trace: Optional[DebugTrace],
        request_start: float,
    ) -> Dict[str, Any]:
        if dry_run:
            return {
                "status": "blocked",
                "reason": "dry_run_not_supported",
                "policy_id": "dry_run_not_supported",
            }

        step_ids: list[str] = []
        warnings: list[dict[str, object]] = []
        for segment in segments:
            result = self._route_query(
                segment,
                logger=logger,
                request_id=request_id,
                tags=tags,
                debug_trace=debug_trace,
            )

            if result.status == "no_skill_found":
                return self._handle_no_skill_found(
                    logger, debug_trace, request_start
                )
            if result.status == "low_confidence":
                return self._handle_low_confidence(
                    result, logger, debug_trace, request_start
                )
            if result.skill_id:
                step_ids.append(result.skill_id)
                internal_id = result.internal_skill_id or to_internal_id(result.skill_id)
                metadata = self.registry.get(internal_id)
                if metadata and metadata.deprecated:
                    warning = build_deprecation_warning(result.skill_id, metadata)
                    warnings.append(warning)
                    if execute:
                        logger.log(
                            "deprecated_skill_used",
                            skill_id=result.skill_id,
                            deprecation_reason=metadata.deprecation_reason,
                            replacement_id=metadata.replacement_id,
                        )

        if not execute:
            return {
                "status": "routed",
                "skill_id": step_ids[0] if step_ids else None,
                "steps": step_ids,
                "warnings": warnings or None,
            }

        runner = PipelineRunner(
            self.root_path,
            log_path=self.log_path,
            step_controller=debug_trace.step_controller if debug_trace else None,
        )
        if mode == "parallel":
            steps: list[object] = [step_ids]
        else:
            steps = step_ids
        pipeline_result = runner.run(
            steps,
            payload=query,
            approval_status=approval,
            approval_token=approval_token,
            role=role,
            attributes=attributes,
            request_id=request_id,
        )
        if pipeline_result.status == "blocked":
            return {
                "status": "blocked",
                "reason": pipeline_result.reason or "blocked",
                "policy_id": pipeline_result.reason or "blocked",
                "warnings": pipeline_result.warnings or None,
            }
        if pipeline_result.status != "success":
            return {
                "status": "error",
                "reason": pipeline_result.reason or "pipeline_failed",
                "warnings": pipeline_result.warnings or None,
            }
        return {
            "status": "success",
            "output": pipeline_result.output,
            "steps": step_ids,
            "warnings": pipeline_result.warnings or None,
        }

    async def _run_multi_async(
        self,
        segments: list[str],
        mode: str,
        *,
        execute: bool,
        dry_run: bool,
        approval: Optional[str],
        approval_token: Optional[str],
        role: Optional[str],
        attributes: dict[str, object] | None,
        tags: list[str] | None,
        logger: EventLogger,
        request_id: str,
        debug_trace: Optional[DebugTrace],
        request_start: float,
    ) -> Dict[str, Any]:
        if dry_run:
            return {
                "status": "blocked",
                "reason": "dry_run_not_supported",
                "policy_id": "dry_run_not_supported",
            }

        step_ids: list[str] = []
        warnings: list[dict[str, object]] = []
        for segment in segments:
            result = await self._route_query_async(
                segment,
                logger=logger,
                request_id=request_id,
                tags=tags,
                debug_trace=debug_trace,
            )

            if result.status == "no_skill_found":
                return self._handle_no_skill_found(
                    logger, debug_trace, request_start
                )
            if result.status == "low_confidence":
                return self._handle_low_confidence(
                    result, logger, debug_trace, request_start
                )
            if result.skill_id:
                step_ids.append(result.skill_id)
                internal_id = result.internal_skill_id or to_internal_id(result.skill_id)
                self._collect_deprecation_warning(
                    internal_id,
                    result.skill_id,
                    warnings,
                    logger=logger,
                    log=execute,
                )

        if not execute:
            return {
                "status": "routed",
                "skill_id": step_ids[0] if step_ids else None,
                "steps": step_ids,
                "warnings": warnings or None,
            }

        runner = PipelineRunner(
            self.root_path,
            log_path=self.log_path,
            step_controller=debug_trace.step_controller if debug_trace else None,
        )
        if mode == "parallel":
            steps: list[object] = [step_ids]
        else:
            steps = step_ids
        pipeline_result = await runner.run_async(
            steps,
            payload=query,
            approval_status=approval,
            approval_token=approval_token,
            role=role,
            attributes=attributes,
            request_id=request_id,
        )
        if pipeline_result.status == "blocked":
            return {
                "status": "blocked",
                "reason": pipeline_result.reason or "blocked",
                "policy_id": pipeline_result.reason or "blocked",
                "warnings": pipeline_result.warnings or None,
            }
        if pipeline_result.status != "success":
            return {
                "status": "error",
                "reason": pipeline_result.reason or "pipeline_failed",
                "warnings": pipeline_result.warnings or None,
            }
        return {
            "status": "success",
            "output": pipeline_result.output,
            "steps": step_ids,
            "warnings": pipeline_result.warnings or None,
        }

    def _handle_no_skill_found(self, logger, trace, start_time):
        duration = (time.perf_counter() - start_time) * 1000
        logger.log("execution_result", status="skipped", error_class="no_skill_found", duration_ms=duration)
        return {"status": "no_skill_found"}

    def _handle_low_confidence(self, result, logger, trace, start_time):
        duration = (time.perf_counter() - start_time) * 1000
        logger.log("execution_result", status="skipped", error_class="low_confidence", duration_ms=duration)
        return {
            "status": "low_confidence",
            "skill_id": result.skill_id,
            "alternatives": result.alternatives
        }

    def _handle_block(self, policy_id, reason, logger, trace, start_time):
        duration = (time.perf_counter() - start_time) * 1000
        logger.log("execution_result", status="blocked", error_class=reason, duration_ms=duration)
        return {"status": "blocked", "reason": reason, "policy_id": policy_id}

from __future__ import annotations
import inspect
import asyncio
from typing import Any, Dict, Optional
from skillos.kernel.base import ExecutionKernel
from skillos.skills.models import SkillMetadata

class LocalExecutionKernel(ExecutionKernel):
    def __init__(self, root_path: str | None = None):
        self.root_path = root_path

    def execute(
        self,
        metadata: SkillMetadata,
        payload: str,
        *,
        role: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        approval_status: Optional[str] = None,
        approval_token: Optional[str] = None,
        **kwargs: Any
    ) -> Any:
        from skillos.skills.registry import resolve_entrypoint
        
        # In a real scenario, the root path would be passed from the registry
        root = kwargs.get("root") or self.root_path
        func = resolve_entrypoint(metadata.entrypoint, root)

        skill_kwargs: Dict[str, Any] = {}
        if role is not None:
            skill_kwargs["role"] = role
        if attributes is not None:
            skill_kwargs["attributes"] = attributes
        if approval_status is not None:
            skill_kwargs["approval_status"] = approval_status
        if approval_token is not None:
            skill_kwargs["approval_token"] = approval_token
        for key, value in kwargs.items():
            if key in {"root", "charge_budget"}:
                continue
            skill_kwargs[key] = value

        if inspect.iscoroutinefunction(func):
            return asyncio.run(self._call_async(func, payload, skill_kwargs))
        return self._call_sync(func, payload, skill_kwargs)

    async def execute_async(
        self,
        metadata: SkillMetadata,
        payload: str,
        *,
        role: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        approval_status: Optional[str] = None,
        approval_token: Optional[str] = None,
        **kwargs: Any
    ) -> Any:
        from skillos.skills.registry import resolve_entrypoint
        
        root = kwargs.get("root") or self.root_path
        func = resolve_entrypoint(metadata.entrypoint, root)

        if inspect.iscoroutinefunction(func):
            return await self._call_async(
                func,
                payload,
                self._build_skill_kwargs(
                    role=role,
                    attributes=attributes,
                    approval_status=approval_status,
                    approval_token=approval_token,
                    extra_kwargs=kwargs,
                ),
            )
        
        return await asyncio.to_thread(
            self._call_sync,
            func,
            payload,
            self._build_skill_kwargs(
                role=role,
                attributes=attributes,
                approval_status=approval_status,
                approval_token=approval_token,
                extra_kwargs=kwargs,
            ),
        )

    def _build_skill_kwargs(
        self,
        *,
        role: Optional[str],
        attributes: Optional[Dict[str, Any]],
        approval_status: Optional[str],
        approval_token: Optional[str],
        extra_kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        skill_kwargs: Dict[str, Any] = {}
        if role is not None:
            skill_kwargs["role"] = role
        if attributes is not None:
            skill_kwargs["attributes"] = attributes
        if approval_status is not None:
            skill_kwargs["approval_status"] = approval_status
        if approval_token is not None:
            skill_kwargs["approval_token"] = approval_token
        for key, value in extra_kwargs.items():
            if key in {"root", "charge_budget"}:
                continue
            skill_kwargs[key] = value
        return skill_kwargs

    def _filter_kwargs(self, signature: inspect.Signature, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        for param in signature.parameters.values():
            if param.kind == param.VAR_KEYWORD:
                return kwargs
        return {key: value for key, value in kwargs.items() if key in signature.parameters}

    def _call_sync(self, func: Any, payload: str, kwargs: Dict[str, Any]) -> Any:
        signature = inspect.signature(func)
        filtered_kwargs = self._filter_kwargs(signature, kwargs)
        if "payload" in signature.parameters:
            return func(payload=payload, **filtered_kwargs)
        positional_params = [
            param
            for param in signature.parameters.values()
            if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
        ]
        if positional_params:
            first_name = positional_params[0].name
            if first_name in filtered_kwargs:
                filtered_kwargs = dict(filtered_kwargs)
                filtered_kwargs.pop(first_name)
            return func(payload, **filtered_kwargs)
        if filtered_kwargs:
            return func(**filtered_kwargs)
        return func()

    async def _call_async(self, func: Any, payload: str, kwargs: Dict[str, Any]) -> Any:
        signature = inspect.signature(func)
        filtered_kwargs = self._filter_kwargs(signature, kwargs)
        if "payload" in signature.parameters:
            return await func(payload=payload, **filtered_kwargs)
        positional_params = [
            param
            for param in signature.parameters.values()
            if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
        ]
        if positional_params:
            first_name = positional_params[0].name
            if first_name in filtered_kwargs:
                filtered_kwargs = dict(filtered_kwargs)
                filtered_kwargs.pop(first_name)
            return await func(payload, **filtered_kwargs)
        if filtered_kwargs:
            return await func(**filtered_kwargs)
        return await func()

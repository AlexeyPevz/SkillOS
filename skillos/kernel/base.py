from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from skillos.skills.models import SkillMetadata

class ExecutionKernel(ABC):
    @abstractmethod
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
        """Synchronously execute the skill."""
        pass

    @abstractmethod
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
        """Asynchronously execute the skill."""
        pass

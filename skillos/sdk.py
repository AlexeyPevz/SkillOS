from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Optional
from pathlib import Path

from skillos.skills.models import SkillMetadata

@dataclass
class Context:
    """Execution context passed to skill functions."""
    role: Optional[str] = None
    attributes: dict[str, object] = None
    request_id: Optional[str] = None
    
    def log(self, message: str, **kwargs):
        # Placeholder for structured logging integration
        print(f"[{self.request_id}] {message} {kwargs}")


def skill(
    name: str = None, 
    description: str = None, 
    version: str = "1.0.0",
    tags: list[str] = None,
    deprecated: bool = False,
    replacement_id: str = None,
    deprecation_reason: str = None,
) -> Callable:
    """
    Decorator to register a function as a SkillOS skill.
    
    Usage:
        @skill(name="my-skill", description="Does something useful")
        def my_skill(payload: str):
            return "Done"
            
    The decorator attaches metadata to the function which can be read by
    loaders or the registry to auto-register the skill without YAML files.
    """
    def decorator(func: Callable) -> Callable:
        # Infer name from function name if not provided
        skill_name = name or func.__name__.replace("_", "-")
        skill_desc = description or (func.__doc__ or "").strip()
        
        # Attach metadata to the function object
        func._skill_metadata = SkillMetadata(
            id=f"local/{skill_name}", # Default to local domain for decorated skills
            name=skill_name,
            description=skill_desc,
            version=version,
            entrypoint=f"{func.__module__}:{func.__name__}",
            tags=tags or [],
            deprecated=deprecated,
            replacement_id=replacement_id,
            deprecation_reason=deprecation_reason,
        )
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Inject context if requested
            sig = inspect.signature(func)
            if "ctx" in sig.parameters and "ctx" not in kwargs:
                # In a real execution, Orchestrator would inject this.
                # For direct calls, we inject a dummy context.
                kwargs["ctx"] = Context(request_id="direct-call")
                
            return func(*args, **kwargs)
            
        return wrapper
    return decorator

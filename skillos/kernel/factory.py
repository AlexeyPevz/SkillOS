from __future__ import annotations
from typing import Dict, Type
from skillos.kernel.base import ExecutionKernel
from skillos.kernel.local import LocalExecutionKernel
from skillos.skills.models import SkillMetadata

_KERNELS: Dict[str, ExecutionKernel] = {}

def get_kernel(metadata: SkillMetadata, root_path: str | None = None) -> ExecutionKernel:
    """Factory to get the appropriate kernel for a skill."""
    mode = getattr(metadata, "execution_mode", "local")
    
    if mode not in _KERNELS:
        if mode == "local":
            _KERNELS[mode] = LocalExecutionKernel(root_path)
        elif mode == "docker":
            raise NotImplementedError("Docker execution kernel is not yet implemented.")
        elif mode == "remote":
            raise NotImplementedError("Remote execution kernel is not yet implemented.")
        else:
            raise ValueError(f"Unknown execution mode: {mode}")
            
    return _KERNELS[mode]

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import inspect
import importlib
from importlib import util as importlib_util
import os
from pathlib import Path
import sys
from typing import Iterable, Any
import asyncio

from skillos.skills.loader import load_skill_file
from skillos.skills.models import SkillMetadata


@dataclass(frozen=True)
class SkillRecord:
    metadata: SkillMetadata
    source: Path


class SkillRegistry:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._skills: dict[str, SkillRecord] = {}
        self._refresh_token: tuple[int, float] | None = None
        # We no longer inject root into sys.path to avoid "Dependency Hell"
        # Modules should be loaded via standard importlib mechanisms or resolved by file path.

    @property
    def root(self) -> Path:
        return self._root

    @property
    def metadata_path(self) -> Path:
        return self._root / "metadata"

    def load_all(self, path: Path | None = None) -> dict[str, SkillRecord]:
        metadata_path = Path(path) if path else self.metadata_path
        if path:
            self._root = metadata_path.parent
                
        self._skills = {}

        # Purge modules to avoid cross-test contamination or stale imports
        self._purge_modules()

        # 1. Load from YAML metadata (Legacy/Standard way)
        if metadata_path.exists():
            for file_path in _iter_skill_files(metadata_path):
                metadata = load_skill_file(file_path)
                self._skills[metadata.id] = SkillRecord(metadata=metadata, source=file_path)

        # 2. Load from Python implementations (Zero-YAML way)
        # Scan 'implementations' folder for functions decorated with @skill
        impl_path = self._root / "implementations"
        if impl_path.exists():
            for py_file in sorted(impl_path.rglob("*.py")):
                # Calculate module name relative to implementations or root
                try:
                    rel_path = py_file.relative_to(self._root)
                    # Handle __init__.py specifically:
                    # implementations/foo/__init__.py -> implementations.foo
                    # implementations/__init__.py -> implementations
                    if py_file.name == "__init__.py":
                         module_name = ".".join(rel_path.parent.parts)
                    else:
                         module_name = ".".join(rel_path.with_suffix("").parts)
                    
                    
                    # Temporarily load module to inspect functions
                    try:
                        module = _load_module_safe(module_name, py_file)
                        
                        for attr_name in dir(module):
                            obj = getattr(module, attr_name)
                            if callable(obj) and hasattr(obj, "_skill_metadata"):
                                metadata = obj._skill_metadata
                                if metadata.id not in self._skills:
                                    self._skills[metadata.id] = SkillRecord(
                                        metadata=metadata, 
                                        source=py_file
                                    )
                    except Exception as e:
                         # Skip files that fail to load, but log it for debug
                         print(f"Failed to load skill from {py_file}: {e}", file=sys.stderr)
                         pass
                except ValueError:
                    continue

        self._refresh_token = self._compute_refresh_token()
        return self._skills

    def reload(self) -> dict[str, SkillRecord]:
        self._purge_modules()
        return self.load_all(self.metadata_path)

    def reload_if_changed(self) -> dict[str, SkillRecord] | None:
        token = self._compute_refresh_token()
        if self._refresh_token is None or token != self._refresh_token:
            return self.load_all(self.metadata_path)
        return None

    def _purge_modules(self) -> None:
        """Purge dynamic skill modules to ensure fresh reloading."""
        to_delete = []
        for m in list(sys.modules.keys()):
            if m.startswith("implementations.") or m == "implementations":
                to_delete.append(m)
        
        for m in to_delete:
            del sys.modules[m]
            
        importlib.invalidate_caches()

    def _compute_refresh_token(self) -> tuple[int, float]:
        files: list[Path] = []
        metadata_path = self.metadata_path
        if metadata_path.exists():
            files.extend(_iter_skill_files(metadata_path))
        implementations_path = self._root / "implementations"
        if implementations_path.exists():
            files.extend(sorted(implementations_path.rglob("*.py")))
        max_mtime = 0.0
        for path in files:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > max_mtime:
                max_mtime = mtime
        return (len(files), max_mtime)

    def get(self, skill_id: str) -> SkillMetadata | None:
        record = self._skills.get(skill_id)
        return record.metadata if record else None

    def search(self, query: str, limit: int = 5) -> list[SkillMetadata]:
        query_lower = query.lower()
        results: list[SkillMetadata] = []
        for record in self._skills.values():
            metadata = record.metadata
            haystack = " ".join(
                [metadata.id, metadata.name, metadata.description, *metadata.tags]
            ).lower()
            if query_lower in haystack:
                results.append(metadata)
        return results[:limit]

    def execute(self, skill_id: str, **kwargs):
        """Synchronous execution entrypoint."""
        from skillos.composition import CompositionEngine, CompositionStore
        from skillos.kernel import get_kernel

        record = self._skills.get(skill_id)
        if not record:
            raise KeyError(f"Unknown skill: {skill_id}")

        allow_inactive = bool(kwargs.pop("allow_inactive", False))
        payload = kwargs.pop("payload", "ok")
        role = kwargs.pop("role", None)
        attributes = kwargs.pop("attributes", None)
        approval_status = kwargs.pop("approval_status", None)
        approval_token = kwargs.pop("approval_token", None)
        charge_budget = kwargs.pop("charge_budget", True)
        session_context = kwargs.pop("session_context", None)
        
        # Composition engine check
        store = CompositionStore(self._root)
        
        with _skill_root_env(self._root):
            if store.exists(skill_id):
                engine = CompositionEngine(self, store)
                return engine.execute(
                    skill_id,
                    payload,
                    allow_inactive=allow_inactive,
                    role=role,
                    attributes=attributes,
                    approval_status=approval_status,
                    approval_token=approval_token,
                    charge_budget=charge_budget,
                    session_context=session_context,
                )
            
            kernel = get_kernel(record.metadata, root_path=str(self._root))
            return kernel.execute(
                record.metadata,
                payload,
                role=role,
                attributes=attributes,
                approval_status=approval_status,
                approval_token=approval_token,
                charge_budget=charge_budget,
                root=self._root,
                session_context=session_context,
                **kwargs
            )

    async def execute_async(self, skill_id: str, **kwargs):
        """Asynchronously execution entrypoint."""
        from skillos.composition import CompositionStore
        from skillos.kernel import get_kernel

        record = self._skills.get(skill_id)
        if not record:
            raise KeyError(f"Unknown skill: {skill_id}")

        store = CompositionStore(self._root)
        
        if store.exists(skill_id):
            # Fallback for composition skills (likely sync)
            return await asyncio.to_thread(self.execute, skill_id, **kwargs)

        kernel = get_kernel(record.metadata, root_path=str(self._root))
        payload = kwargs.pop("payload", "ok")
        role = kwargs.pop("role", None)
        attributes = kwargs.pop("attributes", None)
        approval_status = kwargs.pop("approval_status", None)
        approval_token = kwargs.pop("approval_token", None)
        charge_budget = kwargs.pop("charge_budget", True)
        session_context = kwargs.pop("session_context", None)

        return await kernel.execute_async(
            record.metadata,
            payload,
            role=role,
            attributes=attributes,
            approval_status=approval_status,
            approval_token=approval_token,
            charge_budget=charge_budget,
            root=self._root,
            session_context=session_context,
            **kwargs
        )



def resolve_entrypoint(entrypoint: str, root: Path | None = None) -> Any:
    """Resolve a skill entrypoint string (module:function) to a callable."""
    module_path, func_name = entrypoint.split(":", 1)
    
    # 1. Try standard import first (best practice)
    try:
        module = importlib.import_module(module_path)
        return getattr(module, func_name)
    except ImportError:
        pass
        
    # 2. Try to resolve as a file path relative to root
    if root:
        # Convert dotted path to file path segments
        # e.g. "implementations.chat" -> "implementations/chat.py"
        rel_path = module_path.replace(".", "/") + ".py"
        file_path = (Path(root) / rel_path).resolve()
        
        if file_path.exists():
            return _load_from_file(module_path, file_path, func_name)

        # Fallback: try looking in 'implementations' folder if not specified
        # e.g. "chat" -> "implementations/chat.py"
        if "implementations" not in module_path:
            alt_path = (Path(root) / "implementations" / rel_path).resolve()
            if alt_path.exists():
                return _load_from_file(module_path, alt_path, func_name)

    raise ImportError(
        f"Could not resolve skill entrypoint: {entrypoint}. "
        f"Checked standard imports and relative paths in {root}."
    )


def _load_from_file(module_name: str, file_path: Path, func_name: str) -> Any:
    """Helper to load a module from a specific file path."""
    module = _load_module_safe(module_name, file_path)
    try:
        return getattr(module, func_name)
    except AttributeError:
        raise ImportError(f"Module {module_name} has no attribute '{func_name}'")


def _load_module_safe(module_name: str, file_path: Path) -> Any:
    """
    Safely load a module from a file path, creating parent packages if needed
    and cleaning up sys.modules on failure to prevent poisoning.
    """
    # 1. Ensure parent packages exist in sys.modules to support relative imports
    parts = module_name.split(".")
    for i in range(1, len(parts)):
        parent_name = ".".join(parts[:i])
        if parent_name not in sys.modules:
            # Create a dummy namespace package for the parent
            parent_mod = importlib.util.module_from_spec(
                importlib.util.spec_from_loader(parent_name, loader=None)
            )
            # We assume the parent path is the directory above
            # This is a bit heuristical but necessary for "implementations" root
            try:
                # If we are loading implementations.subdir, parent is implementations
                # We need to find the correct path for it.
                # If parts are ['implementations', 'foo'], i=1 -> 'implementations'
                # parent path is file_path.parents[len(parts) - i] ?
                # Start from file_path directory
                # If path is implementations/foo/bar.py, valid parts are implementations.foo.bar
                # module_name = implementations.foo.bar
                # i=1: parent=implementations. path should optionally point to implementations dir
                # i=2: parent=implementations.foo. path should point to foo dir
                
                # Check if it actually maps to a directory
                depth = len(parts) - i
                if file_path.name == "__init__.py":
                    depth += 1
                    
                parent_dir = file_path.parents[depth-1] # 0 is dir containing file
                if parent_dir.exists():
                    parent_mod.__path__ = [str(parent_dir)]
            except IndexError:
                pass
                
            sys.modules[parent_name] = parent_mod

    spec = importlib_util.spec_from_file_location(module_name, file_path)
    if not spec or not spec.loader:
        raise ImportError(f"Could not create module spec from {file_path}")
    
    module = importlib_util.module_from_spec(spec)
    sys.modules[module_name] = module
    
    try:
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        # CLEANUP: Remove module from sys.modules to prevent poisoning on retry/reload
        # We also attempt to cleanup parents if we just created them, but that's risky if used by others.
        # Minimal safety: remove the leaf node.
        if module_name in sys.modules:
            del sys.modules[module_name]
        raise ImportError(f"Failed to execute module {module_name} from {file_path}: {e}") from e

def _iter_skill_files(metadata_path: Path) -> Iterable[Path]:
    yaml_files = list(metadata_path.rglob("*.yaml"))
    yml_files = list(metadata_path.rglob("*.yml"))
    return sorted(yaml_files + yml_files)

# Update Zero-YAML scanning to calculate correct module name for __init__.py
# (This logic belongs in load_all, updating it there as well logic below implies modification to _load_from_file)





@contextmanager
def _skill_root_env(root: Path) -> Iterable[None]:
    previous = os.environ.get("SKILLOS_ROOT")
    os.environ["SKILLOS_ROOT"] = str(root)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SKILLOS_ROOT", None)
        else:
            os.environ["SKILLOS_ROOT"] = previous

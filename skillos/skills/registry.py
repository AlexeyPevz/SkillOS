from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import inspect
import importlib
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
        # Ensure root is in path for module resolution
        root_str = str(self._root.resolve())
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
            importlib.invalidate_caches()

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
            # Re-ensure root is in path if it changed
            root_str = str(self._root.resolve())
            if root_str not in sys.path:
                sys.path.insert(0, root_str)
                importlib.invalidate_caches()
                
        self._skills = {}

        # Purge modules to avoid cross-test contamination or stale imports
        self._purge_modules()

        if not metadata_path.exists():
            self._refresh_token = self._compute_refresh_token()
            return self._skills

        for file_path in _iter_skill_files(metadata_path):
            metadata = load_skill_file(file_path)
            self._skills[metadata.id] = SkillRecord(metadata=metadata, source=file_path)
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
        """Purge modules related to skills to avoid stale imports and cleanup sys.path."""
        # Purge top-level 'implementations' and its submodules
        # We also need to be careful with 'skillos.skills.implementations' 
        # but in tests it's usually overridden.
        to_delete = []
        for m in list(sys.modules.keys()):
            if m == "implementations" or m.startswith("implementations."):
                to_delete.append(m)
        
        for m in to_delete:
            del sys.modules[m]
            
        # Also cleanup sys.path of any dead tmp_path entries to avoid confusion
        sys.path = [p for p in sys.path if "pytest-" not in str(p) or str(p) == str(self._root.resolve())]
        
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

        allow_inactive = bool(kwargs.pop("allow_inactive", False))
        payload = kwargs.get("payload", "ok")
        role = kwargs.get("role")
        attributes = kwargs.get("attributes")
        approval_status = kwargs.get("approval_status")
        approval_token = kwargs.get("approval_token")
        charge_budget = kwargs.get("charge_budget", True)
        store = CompositionStore(self._root)
        
        with _skill_root_env(self._root):
            if store.exists(skill_id):
                engine = CompositionEngine(self, store)
                # Composition engine might be sync or async, assuming sync for now based on legacy code
                return engine.execute(
                    skill_id,
                    payload,
                    allow_inactive=allow_inactive,
                    role=role,
                    attributes=attributes,
                    approval_status=approval_status,
                    approval_token=approval_token,
                    charge_budget=charge_budget,
                )
            return self._execute_entrypoint(skill_id, payload=payload)

    async def execute_async(self, skill_id: str, **kwargs):
        """Asynchronous execution entrypoint."""
        # Note: Composition engine current implementation status is unknown, 
        # but if it has async methods we should use them. 
        # For now, we wrap the sync execute logic for compositions.
        # Ideally CompositionEngine should also be refactored to support async.
        
        from skillos.composition import CompositionStore
        store = CompositionStore(self._root)
        
        if store.exists(skill_id):
            # Fallback for composition skills (likely sync)
            return await asyncio.to_thread(self.execute, skill_id, **kwargs)

        return await self._execute_entrypoint_async(skill_id, **kwargs)

    def _execute_entrypoint(self, skill_id: str, **kwargs):
        record = self._skills.get(skill_id)
        if not record:
            raise KeyError(f"Unknown skill: {skill_id}")
            
        func = resolve_entrypoint(record.metadata.entrypoint, self._root)
        payload = kwargs.get("payload", "ok")
        
        if inspect.iscoroutinefunction(func):
            # Running async function in sync context
            return asyncio.run(_call_skill_async(func, payload))
        return _call_skill(func, payload)

    async def _execute_entrypoint_async(self, skill_id: str, **kwargs):
        record = self._skills.get(skill_id)
        if not record:
            raise KeyError(f"Unknown skill: {skill_id}")
            
        func = resolve_entrypoint(record.metadata.entrypoint, self._root)
        payload = kwargs.get("payload", "ok")

        if inspect.iscoroutinefunction(func):
             return await _call_skill_async(func, payload)
        
        # Run sync function in thread pool to not block loop
        return await asyncio.to_thread(_call_skill, func, payload)


def resolve_entrypoint(entrypoint: str, root: Path | None = None) -> Any:
    module_path, func_name = entrypoint.split(":", 1)
    if root is not None:
        root_path = Path(root).resolve()
        root_str = str(root_path)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
            importlib.invalidate_caches()
    
    # Try direct import first
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        # Fallback for internal / relative paths
        try:
            # If it's a relative-looking path like "implementations.x", try within skills
            module = importlib.import_module(f"skillos.skills.{module_path}")
        except ImportError:
            # Last ditch effort
            try:
                module = importlib.import_module(f"skillos.{module_path}")
            except ImportError:
                raise ImportError(
                    f"Could not resolve skill entrypoint: {entrypoint}. "
                    f"Original error: {e}. sys.path contains implementations in: "
                    f"{[p for p in sys.path if (Path(p) / 'implementations').exists()]}"
                )

    return getattr(module, func_name)


def _iter_skill_files(metadata_path: Path) -> Iterable[Path]:
    yaml_files = list(metadata_path.rglob("*.yaml"))
    yml_files = list(metadata_path.rglob("*.yml"))
    return sorted(yaml_files + yml_files)


def _call_skill(func, payload: str) -> object:
    signature = inspect.signature(func)
    if "payload" in signature.parameters:
        return func(payload=payload)
    if signature.parameters:
        return func(payload)
    return func()


async def _call_skill_async(func, payload: str) -> object:
    signature = inspect.signature(func)
    if "payload" in signature.parameters:
        return await func(payload=payload)
    if signature.parameters:
        return await func(payload)
    return await func()


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

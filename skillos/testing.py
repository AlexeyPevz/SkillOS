from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import inspect
import json
from pathlib import Path
import sys
import trace
from typing import Callable, Iterable
from unittest.mock import patch

import httpx

from skillos.composition import CompositionStore, execute_composed_skill
from skillos.skills.registry import SkillRegistry, resolve_entrypoint
from skillos.storage import atomic_write_text
from skillos.tenancy import resolve_tenant_root


@dataclass(frozen=True)
class SkillTestResult:
    skill_id: str
    output: str
    coverage_path: Path


def default_coverage_path(root: Path, skill_id: str) -> Path:
    root_path = resolve_tenant_root(root)
    safe_id = skill_id.replace("/", "_")
    return Path(root_path) / "coverage" / f"{safe_id}.json"


def run_skill_test(
    skill_id: str,
    root: Path,
    *,
    payload: str = "ok",
    coverage_path: Path | None = None,
    mock_handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> SkillTestResult:
    registry = SkillRegistry(root)
    registry.load_all()
    metadata = registry.get(skill_id)
    if not metadata:
        raise KeyError(f"Unknown skill: {skill_id}")

    composition_store = CompositionStore(root)
    if composition_store.exists(skill_id):
        source_file = inspect.getsourcefile(execute_composed_skill)
        if not source_file:
            raise ValueError("Unable to resolve composed skill source file")

        def skill_func(payload: str = "ok") -> object:
            return execute_composed_skill(
                skill_id,
                registry,
                payload=payload,
                allow_inactive=True,
            )

    else:
        _purge_module_cache(metadata.entrypoint)
        skill_func = resolve_entrypoint(metadata.entrypoint, Path(root))
        source_file = inspect.getsourcefile(skill_func)
        if not source_file:
            raise ValueError("Unable to resolve skill source file")

    with mock_external_apis(handler=mock_handler):
        output, coverage_summary = _execute_with_coverage(
            skill_id,
            skill_func,
            payload,
            source_file,
        )

    destination = coverage_path or default_coverage_path(root, skill_id)
    atomic_write_text(
        destination,
        json.dumps(coverage_summary, indent=2),
        encoding="utf-8",
    )

    return SkillTestResult(
        skill_id=skill_id,
        output=str(output),
        coverage_path=destination,
    )


@contextmanager
def mock_external_apis(
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> Iterable[None]:
    transport = httpx.MockTransport(handler or _default_httpx_handler)
    original_client = httpx.Client
    original_async_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return original_client(*args, **kwargs)

    def async_client_factory(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return original_async_client(*args, **kwargs)

    def request(method: str, url: str, **kwargs):
        with original_client(transport=transport) as client:
            return client.request(method, url, **kwargs)

    def method_factory(method: str):
        return lambda url, **kwargs: request(method, url, **kwargs)

    patchers = [
        patch("httpx.Client", client_factory),
        patch("httpx.AsyncClient", async_client_factory),
        patch("httpx.request", request),
        patch("httpx.get", method_factory("GET")),
        patch("httpx.post", method_factory("POST")),
        patch("httpx.put", method_factory("PUT")),
        patch("httpx.patch", method_factory("PATCH")),
        patch("httpx.delete", method_factory("DELETE")),
    ]

    for patcher in patchers:
        patcher.start()
    try:
        yield
    finally:
        for patcher in reversed(patchers):
            patcher.stop()


def _default_httpx_handler(request: httpx.Request) -> httpx.Response:
    payload = {
        "mocked": True,
        "method": request.method,
        "url": str(request.url),
    }
    return httpx.Response(200, json=payload)


def _execute_with_coverage(
    skill_id: str,
    skill_func: Callable[..., object],
    payload: str,
    source_file: str,
) -> tuple[object, dict]:
    tracer = trace.Trace(count=True, trace=False)
    output = tracer.runfunc(_call_skill, skill_func, payload)
    results = tracer.results()
    executed_lines = _executed_lines(results, source_file)
    total_lines = _count_nonempty_lines(Path(source_file))
    coverage_ratio = (
        len(executed_lines) / total_lines if total_lines > 0 else 1.0
    )
    summary = {
        "skill_id": skill_id,
        "entrypoint": f"{skill_func.__module__}:{skill_func.__name__}",
        "source_file": str(Path(source_file)),
        "executed_lines": executed_lines,
        "total_lines": total_lines,
        "coverage_ratio": round(coverage_ratio, 3),
    }
    return output, summary


def _call_skill(skill_func: Callable[..., object], payload: str) -> object:
    signature = inspect.signature(skill_func)
    if "payload" in signature.parameters:
        return skill_func(payload=payload)
    if signature.parameters:
        return skill_func(payload)
    return skill_func()


def _purge_module_cache(entrypoint: str) -> None:
    module_path = entrypoint.split(":", 1)[0]
    parts = module_path.split(".")
    for index in range(1, len(parts) + 1):
        sys.modules.pop(".".join(parts[:index]), None)


def _executed_lines(results: trace.CoverageResults, source_file: str) -> list[int]:
    source_path = Path(source_file).resolve()
    return sorted(
        lineno
        for (filename, lineno), count in results.counts.items()
        if count > 0 and Path(filename).resolve() == source_path
    )


def _count_nonempty_lines(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    return sum(1 for line in lines if line.strip())

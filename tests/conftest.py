from __future__ import annotations

import json
from pathlib import Path
import sys
import os

# Add project root to sys.path so 'skillos' package is resolvable
project_root = str(Path(__file__).parent.parent.resolve())
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import asyncio
import inspect
import pytest
import yaml

_CATALOG_PATH = Path("tests/fixtures/skills/golden_skill_catalog.json")


def load_skill_catalog() -> list[dict]:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def write_skill_catalog(root: Path, catalog: list[dict]) -> None:
    for skill in catalog:
        skill_id = skill["id"]
        domain, name = skill_id.split("/", 1)
        metadata_dir = root / "metadata" / domain
        metadata_dir.mkdir(parents=True, exist_ok=True)
        metadata_file = metadata_dir / f"{name}.yaml"
        metadata_file.write_text(
            yaml.safe_dump(skill, sort_keys=False),
            encoding="utf-8",
        )
        
        # Generate dummy implementation
        entrypoint = skill.get("entrypoint")
        if entrypoint and ":" in entrypoint:
            module_path, func = entrypoint.split(":", 1)
            parts = module_path.split(".")
            impl_file = root.joinpath(*parts).with_suffix(".py")
            impl_file.parent.mkdir(parents=True, exist_ok=True)
            if not impl_file.exists():
                impl_file.write_text(
                    f"def {func}(payload='ok', **kwargs): return {{'status': 'success', 'data': payload, 'skill': '{skill_id}'}}",
                    encoding="utf-8"
                )


@pytest.fixture()
def skill_catalog() -> list[dict]:
    return load_skill_catalog()


@pytest.fixture()
def skill_root(tmp_path: Path, skill_catalog: list[dict]) -> Path:
    root = tmp_path / "skills"
    write_skill_catalog(root, skill_catalog)
    return root


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("asyncio_mode", "Fallback asyncio mode", default="auto")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "asyncio: run async test function in an event loop (fallback)",
    )


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    if pyfuncitem.config.pluginmanager.hasplugin("pytest_asyncio"):
        return None
    if pyfuncitem.get_closest_marker("asyncio") is None:
        return None
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None

    signature = inspect.signature(pyfuncitem.obj)
    if any(
        param.kind == param.VAR_KEYWORD
        for param in signature.parameters.values()
    ):
        kwargs = pyfuncitem.funcargs
    else:
        kwargs = {
            name: pyfuncitem.funcargs[name]
            for name in signature.parameters
            if name in pyfuncitem.funcargs
        }

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(pyfuncitem.obj(**kwargs))
    finally:
        loop.close()
        asyncio.set_event_loop(None)
    return True

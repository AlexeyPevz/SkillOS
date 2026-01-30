import pytest
from uuid import uuid4

from skillos.kernel.local import LocalExecutionKernel
from skillos.skills.models import SkillMetadata


def _write_module(tmp_path, module_name: str, source: str) -> str:
    parts = module_name.split(".")
    module_file = tmp_path
    for segment in parts[:-1]:
        module_file = module_file / segment
    module_file.mkdir(parents=True, exist_ok=True)
    file_path = module_file / f"{parts[-1]}.py"
    file_path.write_text(source, encoding="utf-8")
    return file_path.as_posix()


def _make_metadata(entrypoint: str) -> SkillMetadata:
    return SkillMetadata(
        id=f"test/{uuid4().hex}",
        name="Test Skill",
        description="test",
        version="1.0.0",
        entrypoint=entrypoint,
    )


def test_kernel_passes_session_context_and_filters_kwargs(tmp_path):
    module = f"implementations.ctx_{uuid4().hex}"
    _write_module(
        tmp_path,
        module,
        "def run(payload='ok', session_context=None, role=None, **kwargs):\n"
        "    return {\n"
        "        'payload': payload,\n"
        "        'session': session_context,\n"
        "        'role': role,\n"
        "        'extra': kwargs.get('extra'),\n"
        "    }\n",
    )
    meta = _make_metadata(f"{module}:run")
    kernel = LocalExecutionKernel(root_path=str(tmp_path))

    result = kernel.execute(
        meta,
        "ping",
        role="admin",
        session_context={"k": "v"},
        extra="ok",
        charge_budget=False,
    )

    assert result["payload"] == "ping"
    assert result["session"] == {"k": "v"}
    assert result["role"] == "admin"
    assert result["extra"] == "ok"


def test_kernel_ignores_unexpected_kwargs(tmp_path):
    module = f"implementations.simple_{uuid4().hex}"
    _write_module(
        tmp_path,
        module,
        "def run(payload='ok'):\n"
        "    return payload\n",
    )
    meta = _make_metadata(f"{module}:run")
    kernel = LocalExecutionKernel(root_path=str(tmp_path))

    result = kernel.execute(
        meta,
        "hello",
        role="admin",
        session_context={"a": 1},
        extra="ignored",
    )
    assert result == "hello"


def test_kernel_supports_positional_payload(tmp_path):
    module = f"implementations.pos_{uuid4().hex}"
    _write_module(
        tmp_path,
        module,
        "def run(value):\n"
        "    return value\n",
    )
    meta = _make_metadata(f"{module}:run")
    kernel = LocalExecutionKernel(root_path=str(tmp_path))

    result = kernel.execute(meta, "positional", session_context={"x": 1})
    assert result == "positional"


@pytest.mark.anyio
async def test_kernel_execute_async_with_context(tmp_path):
    module = f"implementations.async_{uuid4().hex}"
    _write_module(
        tmp_path,
        module,
        "async def run(payload='ok', session_context=None):\n"
        "    value = session_context.get('id') if session_context else None\n"
        "    return f\"{payload}:{value}\"\n",
    )
    meta = _make_metadata(f"{module}:run")
    kernel = LocalExecutionKernel(root_path=str(tmp_path))

    result = await kernel.execute_async(
        meta,
        "async",
        session_context={"id": "42"},
        extra="ignored",
    )
    assert result == "async:42"

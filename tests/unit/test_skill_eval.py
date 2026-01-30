from uuid import uuid4

import pytest

from skillos.skills.eval import run_skill_eval, save_eval_result, SkillEvalError


def _write_module(tmp_path, module_name: str, source: str) -> None:
    parts = module_name.split(".")
    module_dir = tmp_path
    for segment in parts[:-1]:
        module_dir = module_dir / segment
    module_dir.mkdir(parents=True, exist_ok=True)
    file_path = module_dir / f"{parts[-1]}.py"
    file_path.write_text(source, encoding="utf-8")


def test_run_skill_eval_success(tmp_path):
    skills_root = tmp_path
    (skills_root / "metadata" / "test").mkdir(parents=True, exist_ok=True)
    (skills_root / "implementations").mkdir(parents=True, exist_ok=True)

    module_name = f"implementations.eval_{uuid4().hex}"
    _write_module(
        skills_root,
        module_name,
        "def run(payload='ok'):\n"
        "    return f'result={payload} 105'\n",
    )

    metadata_path = skills_root / "metadata" / "test" / "eval.yaml"
    metadata_path.write_text(
        "\n".join(
            [
                "id: test/eval",
                "name: Eval",
                "description: test",
                "version: 1.0.0",
                f"entrypoint: {module_name}:run",
                "eval:",
                "  pass_threshold: 0.5",
                "  cases:",
                "    - input: hello",
                "      expected: result=hello 105",
                "      match: equals",
                "    - input: ignored",
                "      match: numeric_range",
                "      range: [100, 120]",
            ]
        ),
        encoding="utf-8",
    )

    result = run_skill_eval("test/eval", skills_root)
    assert result.total == 2
    assert result.passed == 2
    assert result.success_rate == 1.0
    assert result.ok

    saved_path = save_eval_result(result, skills_root)
    assert saved_path.exists()


def test_run_skill_eval_missing_config(tmp_path):
    skills_root = tmp_path
    (skills_root / "metadata" / "test").mkdir(parents=True, exist_ok=True)
    (skills_root / "implementations").mkdir(parents=True, exist_ok=True)

    module_name = f"implementations.eval_{uuid4().hex}"
    _write_module(
        skills_root,
        module_name,
        "def run(payload='ok'):\n"
        "    return payload\n",
    )

    metadata_path = skills_root / "metadata" / "test" / "eval.yaml"
    metadata_path.write_text(
        "\n".join(
            [
                "id: test/eval",
                "name: Eval",
                "description: test",
                "version: 1.0.0",
                f"entrypoint: {module_name}:run",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(SkillEvalError, match="eval_not_configured"):
        run_skill_eval("test/eval", skills_root)


def test_run_skill_eval_regex_numeric_and_limits(tmp_path):
    skills_root = tmp_path
    (skills_root / "metadata" / "test").mkdir(parents=True, exist_ok=True)
    (skills_root / "implementations").mkdir(parents=True, exist_ok=True)

    module_name = f"implementations.eval_{uuid4().hex}"
    _write_module(
        skills_root,
        module_name,
        "def run(payload='ok'):\n"
        "    return 'price: 150 units'\n",
    )

    metadata_path = skills_root / "metadata" / "test" / "eval.yaml"
    metadata_path.write_text(
        "\n".join(
            [
                "id: test/eval",
                "name: Eval",
                "description: test",
                "version: 1.0.0",
                f"entrypoint: {module_name}:run",
                "eval:",
                "  pass_threshold: 0.5",
                "  max_cases: 1",
                "  cases:",
                "    - input: hello",
                "      expected: 'price:\\s*(\\d+)'",
                "      match: regex_numeric",
                "      range: [100, 200]",
            ]
        ),
        encoding="utf-8",
    )

    result = run_skill_eval("test/eval", skills_root)
    assert result.total == 1
    assert result.passed == 1
    assert result.ok


def test_run_skill_eval_timeout(tmp_path):
    import time

    skills_root = tmp_path
    (skills_root / "metadata" / "test").mkdir(parents=True, exist_ok=True)
    (skills_root / "implementations").mkdir(parents=True, exist_ok=True)

    module_name = f"implementations.eval_{uuid4().hex}"
    _write_module(
        skills_root,
        module_name,
        "import time\n"
        "def run(payload='ok'):\n"
        "    time.sleep(0.2)\n"
        "    return 'done'\n",
    )

    metadata_path = skills_root / "metadata" / "test" / "eval.yaml"
    metadata_path.write_text(
        "\n".join(
            [
                "id: test/eval",
                "name: Eval",
                "description: test",
                "version: 1.0.0",
                f"entrypoint: {module_name}:run",
                "eval:",
                "  pass_threshold: 1.0",
                "  timeout_seconds: 0.05",
                "  cases:",
                "    - input: hello",
                "      expected: done",
                "      match: equals",
            ]
        ),
        encoding="utf-8",
    )

    result = run_skill_eval("test/eval", skills_root)
    assert result.total == 1
    assert result.passed == 0
    assert not result.ok
    assert result.cases[0].details == "timeout"

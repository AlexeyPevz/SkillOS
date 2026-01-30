from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import httpx

from skillos.skills.models import SkillEvalConfig, SkillMetadata
from skillos.skills.registry import SkillRegistry
from skillos.storage import atomic_write_text
from skillos.testing import mock_external_apis

_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\d*\.?\d+)")


class SkillEvalError(ValueError):
    pass


@dataclass(frozen=True)
class EvalCaseResult:
    input: str
    expected: str | None
    match: str
    passed: bool
    output: str
    details: str | None = None


@dataclass(frozen=True)
class EvalRunResult:
    skill_id: str
    total: int
    passed: int
    success_rate: float
    pass_threshold: float
    cases: list[EvalCaseResult]

    @property
    def ok(self) -> bool:
        return self.success_rate >= self.pass_threshold

    def to_dict(self) -> dict[str, object]:
        return {
            "skill_id": self.skill_id,
            "total": self.total,
            "passed": self.passed,
            "success_rate": self.success_rate,
            "pass_threshold": self.pass_threshold,
            "ok": self.ok,
            "cases": [
                {
                    "input": case.input,
                    "expected": case.expected,
                    "match": case.match,
                    "passed": case.passed,
                    "output": case.output,
                    "details": case.details,
                }
                for case in self.cases
            ],
        }


def run_skill_eval(
    skill_id: str,
    root: Path,
    *,
    eval_config: SkillEvalConfig | None = None,
    mock_handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> EvalRunResult:
    registry = SkillRegistry(root)
    registry.load_all()
    metadata = registry.get(skill_id)
    if not metadata:
        raise KeyError(f"Unknown skill: {skill_id}")

    config = eval_config or metadata.eval
    if not config or not config.cases:
        raise SkillEvalError("eval_not_configured")

    results: list[EvalCaseResult] = []
    cases = config.cases
    if config.max_cases is not None:
        cases = cases[: config.max_cases]
    timeout_seconds = config.timeout_seconds
    with mock_external_apis(handler=mock_handler):
        for case in cases:
            output_text, details = _execute_case(
                registry,
                skill_id,
                case.input,
                timeout_seconds,
            )
            if output_text is None:
                results.append(
                    EvalCaseResult(
                        input=case.input,
                        expected=case.expected,
                        match=case.match,
                        passed=False,
                        output="",
                        details=details or "execution_failed",
                    )
                )
                if config.fail_fast:
                    break
                continue
            passed, details = _match_case(case, output_text)
            results.append(
                EvalCaseResult(
                    input=case.input,
                    expected=case.expected,
                    match=case.match,
                    passed=passed,
                    output=output_text,
                    details=details,
                )
            )
            if config.fail_fast and not passed:
                break

    passed_count = sum(1 for item in results if item.passed)
    total = len(results)
    success_rate = passed_count / total if total else 0.0
    return EvalRunResult(
        skill_id=skill_id,
        total=total,
        passed=passed_count,
        success_rate=round(success_rate, 3),
        pass_threshold=config.pass_threshold,
        cases=results,
    )


def _execute_case(
    registry: SkillRegistry,
    skill_id: str,
    payload: str,
    timeout_seconds: float | None,
) -> tuple[str | None, str | None]:
    if timeout_seconds is None:
        return str(registry.execute(skill_id, payload=payload)), None

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(registry.execute, skill_id, payload=payload)
        try:
            return str(future.result(timeout=timeout_seconds)), None
        except FutureTimeoutError:
            future.cancel()
            return None, "timeout"
        except Exception as exc:
            return None, exc.__class__.__name__


def default_eval_result_path(root: Path, skill_id: str) -> Path:
    safe_id = skill_id.replace("/", "_")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(root) / "runtime" / "evals" / f"{safe_id}-{timestamp}.json"


def save_eval_result(
    result: EvalRunResult,
    root: Path,
    *,
    output_path: Path | None = None,
) -> Path:
    destination = output_path or default_eval_result_path(root, result.skill_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        destination,
        json.dumps(result.to_dict(), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return destination


def _match_case(case, output: str) -> tuple[bool, str | None]:
    match = case.match
    if match == "equals":
        expected = str(case.expected).strip() if case.expected is not None else ""
        ok = output.strip() == expected
        return ok, None if ok else f"expected '{expected}'"
    if match == "contains":
        expected = str(case.expected) if case.expected is not None else ""
        ok = expected in output
        return ok, None if ok else f"missing '{expected}'"
    if match == "regex":
        pattern = str(case.expected) if case.expected is not None else ""
        ok = re.search(pattern, output) is not None
        return ok, None if ok else f"regex '{pattern}' not matched"
    if match == "regex_numeric":
        pattern = str(case.expected) if case.expected is not None else ""
        found = re.search(pattern, output)
        if not found:
            return False, f"regex '{pattern}' not matched"
        group_index = case.group if case.group is not None else 1
        try:
            token = found.group(group_index)
        except IndexError:
            return False, f"group {group_index} not found"
        try:
            number = float(token)
        except ValueError:
            return False, f"non_numeric_group '{token}'"
        low, high = case.range
        ok = low <= number <= high
        return ok, None if ok else f"number {number} not in [{low}, {high}]"
    if match == "numeric_range":
        number = _extract_number(output)
        if number is None:
            return False, "no_number_found"
        low, high = case.range
        ok = low <= number <= high
        return ok, None if ok else f"number {number} not in [{low}, {high}]"
    return False, "unknown_matcher"


def _extract_number(text: str) -> float | None:
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None

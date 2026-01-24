from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import time
from typing import Callable, Iterable


PromptFn = Callable[[str], None]


def _default_step_prompt(message: str) -> None:
    input(f"{message} (press Enter) ")


@dataclass(frozen=True)
class StepController:
    prompt: PromptFn = _default_step_prompt
    show_inputs: bool = False
    show_outputs: bool = False
    show_timing: bool = False

    def pause(
        self,
        name: str,
        *,
        inputs: dict[str, object] | None = None,
        outputs: dict[str, object] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        parts = [f"step: {name}"]
        if self.show_inputs and inputs is not None:
            parts.append(
                f"inputs={json.dumps(inputs, ensure_ascii=True, default=str)}"
            )
        if self.show_outputs and outputs is not None:
            parts.append(
                f"outputs={json.dumps(outputs, ensure_ascii=True, default=str)}"
            )
        if self.show_timing and duration_ms is not None:
            parts.append(f"duration_ms={duration_ms:.2f}")
        self.prompt(" | ".join(parts))


@dataclass(frozen=True)
class DebugTraceConfig:
    capture_inputs: bool
    capture_outputs: bool
    capture_timing: bool


@dataclass(frozen=True)
class TraceStep:
    name: str
    inputs: dict[str, object] | None
    outputs: dict[str, object] | None
    duration_ms: float | None


@dataclass
class DebugTrace:
    config: DebugTraceConfig
    step_controller: StepController | None = None
    steps: list[TraceStep] = field(default_factory=list)

    def add_step(
        self,
        name: str,
        *,
        inputs: dict[str, object] | None = None,
        outputs: dict[str, object] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        self.steps.append(
            TraceStep(
                name=name,
                inputs=inputs if self.config.capture_inputs else None,
                outputs=outputs if self.config.capture_outputs else None,
                duration_ms=duration_ms if self.config.capture_timing else None,
            )
        )

    @contextmanager
    def step(
        self, name: str, *, inputs: dict[str, object] | None = None
    ) -> Iterable[dict[str, object]]:
        start = time.perf_counter()
        outputs: dict[str, object] = {}
        try:
            yield outputs
        finally:
            capture_timing = self.config.capture_timing or (
                self.step_controller and self.step_controller.show_timing
            )
            duration_ms = (
                (time.perf_counter() - start) * 1000 if capture_timing else None
            )
            self.add_step(
                name,
                inputs=inputs,
                outputs=outputs,
                duration_ms=duration_ms,
            )
            if self.step_controller:
                self.step_controller.pause(
                    name,
                    inputs=inputs if self.config.capture_inputs else None,
                    outputs=outputs if self.config.capture_outputs else None,
                    duration_ms=duration_ms,
                )


@contextmanager
def trace_step(
    trace: DebugTrace | None,
    name: str,
    *,
    inputs: dict[str, object] | None = None,
) -> Iterable[dict[str, object]]:
    if trace is None:
        yield {}
        return
    with trace.step(name, inputs=inputs) as outputs:
        yield outputs


def render_trace(trace: DebugTrace) -> str:
    lines = ["trace:"]
    for step in trace.steps:
        line = f"- {step.name}"
        if step.duration_ms is not None:
            line += f" ({step.duration_ms:.2f}ms)"
        lines.append(line)
        if step.inputs is not None:
            lines.append(
                f"  inputs: {json.dumps(step.inputs, ensure_ascii=True)}"
            )
        if step.outputs is not None:
            lines.append(
                f"  outputs: {json.dumps(step.outputs, ensure_ascii=True)}"
            )
    return "\n".join(lines)

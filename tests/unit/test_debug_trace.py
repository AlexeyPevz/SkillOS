from skillos.debugging import (
    DebugTrace,
    DebugTraceConfig,
    StepController,
    trace_step,
)


def test_debug_trace_preserves_step_order() -> None:
    trace = DebugTrace(
        DebugTraceConfig(
            capture_inputs=True,
            capture_outputs=True,
            capture_timing=True,
        )
    )

    with trace_step(trace, "route", inputs={"query": "hello"}) as outputs:
        outputs["skill_id"] = "demo/hello"
    with trace_step(trace, "budget_check", inputs={"dry_run": False}) as outputs:
        outputs["allowed"] = True

    assert [step.name for step in trace.steps] == ["route", "budget_check"]


def test_step_controller_pauses_after_step() -> None:
    prompts: list[str] = []
    controller = StepController(
        prompt=prompts.append,
        show_inputs=True,
        show_outputs=True,
        show_timing=True,
    )
    trace = DebugTrace(
        DebugTraceConfig(
            capture_inputs=True,
            capture_outputs=True,
            capture_timing=False,
        ),
        step_controller=controller,
    )

    with trace_step(trace, "route", inputs={"query": "hello"}) as outputs:
        outputs["skill_id"] = "demo/hello"

    assert len(prompts) == 1
    assert "step: route" in prompts[0]
    assert "inputs=" in prompts[0]
    assert "outputs=" in prompts[0]
    assert "duration_ms=" in prompts[0]

from pathlib import Path

from skillos.cli import cli


def test_debug_run_captures_inputs_outputs(skill_root: Path, tmp_path: Path) -> None:
    query = "Find flights to Sochi"
    log_path = tmp_path / "debug.log"

    run_callback = cli.commands["run"].callback
    trace = run_callback(
        query,
        skill_root,
        log_path,
        execute=False,
        dry_run=False,
        approval=None,
        approval_token=None,
        role=None,
        tags=(),
        mode="single",
        plan_path=None,
        debug=True,
        profile=False,
        show_trace=False,
        step_through=False,
        jwt_token=None,
    )

    assert trace is not None
    assert trace.steps
    assert all(step.inputs is not None for step in trace.steps)
    assert all(step.outputs is not None for step in trace.steps)

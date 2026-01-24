from __future__ import annotations
from pathlib import Path
import click

from skillos.skills.paths import default_skills_root
from skillos.approval_gate import approval_token_from_env
from skillos.composition import (
    compose_skill as compose_skill_impl, 
    CompositionError,
    activate_composed_skill
)
from skillos.pipeline import PipelineRunner, PipelineError
from skillos.debugging import StepController
from skillos.cli.utils import (
    _apply_auth_context,
    _emit_warnings,
    _blocked_message,
    _approval_message
)

def _parse_composition_steps(steps: tuple[str, ...]) -> list[object]:
    parsed: list[object] = []
    for step in steps:
        parts = [part.strip() for part in step.split("|")]
        if len(parts) == 1:
            parsed.append(parts[0])
        else:
            parsed.append(parts)
    return parsed

@click.command("compose-skill")
@click.argument("skill_id")
@click.option(
    "--step",
    "steps",
    multiple=True,
    required=True,
)
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
@click.option("--name", default=None)
@click.option("--description", default=None)
def compose_skill(
    skill_id: str,
    steps: tuple[str, ...],
    root_path: Path,
    name: str | None,
    description: str | None,
) -> None:
    """Create a composed skill from existing skills."""
    try:
        spec = compose_skill_impl(
            root_path,
            skill_id,
            _parse_composition_steps(steps),
            name=name,
            description=description,
        )
    except CompositionError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"composed_skill_created: {spec.skill_id} version={spec.version}")

@click.command("activate-skill")
@click.argument("skill_id")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
@click.option(
    "--approval",
    type=click.Choice(["approved", "denied"], case_sensitive=False),
    default=None,
)
@click.option("--approval-token", default=None)
def activate_skill(
    skill_id: str,
    root_path: Path,
    approval: str | None,
    approval_token: str | None,
) -> None:
    """Activate a composed skill after approval."""
    try:
        result = activate_composed_skill(
            root_path,
            skill_id,
            approval_status=approval,
            approval_token=approval_token,
            required_token=approval_token_from_env(),
        )
    except CompositionError as exc:
        raise click.ClickException(str(exc)) from exc
    if not result.activated:
        if result.status == "tests_required":
            raise click.ClickException("tests_required")
        raise click.ClickException(_approval_message(result.approval.policy_id))
    click.echo(f"activation_success: {skill_id}")


@click.group("pipeline")
def pipeline() -> None:
    """Run a pipeline of skills."""


@pipeline.command("run")
@click.option(
    "--step",
    "steps",
    multiple=True,
    required=True,
    help="Pipeline step skill id. Use `|` to run steps in parallel.",
)
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
@click.option(
    "--log-path",
    "log_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
)
@click.option("--payload", default="ok", show_default=True)
@click.option(
    "--approval",
    type=click.Choice(["approved", "denied"], case_sensitive=False),
    default=None,
)
@click.option("--approval-token", default=None)
@click.option("--role", default=None)
@click.option(
    "--step-through/--no-step-through",
    "step_through",
    default=False,
    show_default=True,
)
@click.option("--jwt", "jwt_token", default=None)
def pipeline_run(
    steps: tuple[str, ...],
    root_path: Path,
    log_path: Path | None,
    payload: str,
    approval: str | None,
    approval_token: str | None,
    role: str | None,
    step_through: bool,
    jwt_token: str | None,
) -> None:
    """Execute a sequential/parallel pipeline with context passing."""
    root_path, role, attributes = _apply_auth_context(root_path, role, jwt_token)
    step_controller = None
    if step_through:
        step_controller = StepController(
            show_inputs=True,
            show_outputs=True,
            show_timing=False,
        )
    runner = PipelineRunner(
        root_path,
        log_path=log_path,
        step_controller=step_controller,
    )
    try:
        result = runner.run(
            steps,
            payload=payload,
            approval_status=approval,
            approval_token=approval_token,
            role=role,
            attributes=attributes,
        )
    except PipelineError as exc:
        raise click.ClickException(str(exc)) from exc

    _emit_warnings(result.warnings)
    if result.status == "blocked":
        reason = result.reason or "blocked"
        click.echo(f"blocked: {_blocked_message(reason)}")
        return
    if result.status != "success":
        raise click.ClickException(result.reason or "pipeline_failed")
    click.echo(result.output)

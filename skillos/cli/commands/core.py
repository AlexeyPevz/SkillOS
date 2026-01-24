from __future__ import annotations
from pathlib import Path
import click

from skillos.skills.paths import default_skills_root
from skillos.debugging import DebugTraceConfig, DebugTrace, StepController, render_trace
from skillos.orchestrator import Orchestrator
from skillos.cli.utils import (
    _apply_auth_context,
    _emit_warnings,
    _blocked_message
)


@click.command("run")
@click.argument("query")
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
@click.option("--execute/--no-execute", default=False, show_default=True)
@click.option("--dry-run/--no-dry-run", default=False, show_default=True)
@click.option(
    "--approval",
    type=click.Choice(["approved", "denied"], case_sensitive=False),
    default=None,
)
@click.option("--approval-token", default=None)
@click.option("--role", default=None)
@click.option("--tag", "tags", multiple=True)
@click.option(
    "--mode",
    type=click.Choice(["single", "pipeline", "parallel", "auto"], case_sensitive=False),
    default="single",
    show_default=True,
)
@click.option(
    "--plan-path",
    "plan_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
)
@click.option("--debug/--no-debug", default=False, show_default=True)
@click.option("--profile/--no-profile", default=False, show_default=True)
@click.option(
    "--trace/--no-trace",
    "show_trace",
    default=False,
    show_default=True,
)
@click.option(
    "--step-through/--no-step-through",
    "step_through",
    default=False,
    show_default=True,
)
@click.option("--jwt", "jwt_token", default=None)
def run_query(
    query: str,
    root_path: Path,
    log_path: Path | None,
    execute: bool,
    dry_run: bool,
    approval: str | None,
    approval_token: str | None,
    role: str | None,
    tags: tuple[str, ...],
    mode: str,
    plan_path: Path | None,
    debug: bool,
    profile: bool,
    show_trace: bool,
    step_through: bool,
    jwt_token: str | None,
) -> DebugTrace | None:
    """Route a query to the best skill."""
    
    trace_config = DebugTraceConfig(
        capture_inputs=debug or step_through,
        capture_outputs=debug or step_through,
        capture_timing=profile,
    )
    step_controller = None
    if step_through:
        step_controller = StepController(
            show_inputs=debug or step_through,
            show_outputs=debug or step_through,
            show_timing=profile,
        )
    debug_trace = (
        DebugTrace(trace_config, step_controller=step_controller)
        if (debug or profile or show_trace or step_through)
        else None
    )
    
    try:
        root_path, role, attributes = _apply_auth_context(
            root_path, role, jwt_token
        )
        orchestrator = Orchestrator(root_path, log_path)
        result = orchestrator.run_query(
            query=query,
            execute=execute,
            dry_run=dry_run,
            approval=approval,
            approval_token=approval_token,
            role=role,
            attributes=attributes,
            tags=list(tags) if tags else None,
            mode=mode,
            plan_path=plan_path,
            debug_trace=debug_trace,
        )
        
        status = result.get("status")
        _emit_warnings(result.get("warnings"))
        
        if status == "no_skill_found":
            click.echo("no_skill_found")
            return debug_trace
            
        if status == "low_confidence":
            click.echo(f"low_confidence: {result['skill_id']}")
            alternatives = ", ".join(result.get("alternatives", [])) or "none"
            click.echo(f"alternatives: {alternatives}")
            return debug_trace
            
        if status == "blocked":
            reason = result.get("reason") or result.get("policy_id") or "blocked"
            click.echo(f"blocked: {_blocked_message(reason)}")
            return debug_trace
            
        # Success or Dry Run or Routed
        click.echo(result.get("skill_id"))

        if status == "dry_run":
            if result.get("preview"):
                preview = result["preview"]
                click.echo(f"plan_id: {preview.plan_id}")
                click.echo("affected_entities:")
                for entity in preview.affected_entities:
                    click.echo(f"- {entity}")
            if result.get("plan_path"):
                 click.echo(f"plan_written: {result['plan_path']}")
        
        elif status == "success":
            if result.get("plan_id"):
                 click.echo(f"plan_id: {result['plan_id']}")
            click.echo(result.get("output"))
        elif status == "error":
            raise click.ClickException(result.get("reason") or "execution_failed")
            
    except click.ClickException:
        raise
    except Exception as e:
        if debug:
            raise
        click.echo(f"Error: {str(e)}", err=True)
    finally:
        if show_trace and debug_trace:
            click.echo(render_trace(debug_trace))
            
    return debug_trace

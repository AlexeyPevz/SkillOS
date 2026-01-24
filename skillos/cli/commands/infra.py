from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import time
import click

from skillos.skills.paths import default_skills_root
from skillos.secrets_wizard import build_secret_prompts, update_secrets_file, update_env_example
from skillos.connectors import default_secrets_path, ConnectorNotFoundError, ConnectorError
from skillos.context_monitor import (
    ContextMonitor,
    ContextMonitorError,
    load_context_signals,
)
from skillos.scheduler import SuggestionScheduler
from skillos.suggestions import (
    suggestion_store_from_env,
    preferences_store_from_env,
)
from skillos.notification import NotificationCenter
from skillos.schedules import (
    ScheduleRecord,
    build_schedule,
    due_schedules,
    parse_run_at,
    schedule_store_from_env,
)
from skillos.webhooks import (
    handle_webhook_event,
    WebhookSignatureError,
    WebhookPayloadError,
    WebhookTriggerError,
)
from skillos.jobs import JobRecord, job_store_from_env
from skillos.telemetry import (
    EventLogger, 
    default_log_path, 
    new_request_id,
    log_job_enqueued,
    log_schedule_due,
    log_schedule_started,
    log_schedule_failed,
    log_schedule_completed,
)
from skillos.execution_planner import build_execution_plan
from skillos.orchestrator import Orchestrator
from skillos.routing import to_internal_id, to_public_id

# Helpers
def _format_schedule_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()

def _emit_schedule_result(record: ScheduleRecord, success: bool) -> None:
    if success:
        click.echo(f"schedule_completed: {record.schedule_id}")
    else:
        click.echo(f"schedule_failed: {record.schedule_id}")

def _emit_job_result(record: JobRecord) -> None:
    if record.status == "succeeded":
        click.echo(f"job_succeeded: {record.job_id}")
    elif record.status == "queued":
        click.echo(f"job_retry_scheduled: {record.job_id}")
    else:
        click.echo(f"job_failed: {record.job_id}")

def _execute_schedule(
    record: ScheduleRecord,
    *,
    orchestrator: Orchestrator,
    log_path: Path,
) -> tuple[bool, str | None]:
    now = datetime.now(timezone.utc)
    due_at = record.due_at()
    lag_ms = max(0.0, (now - due_at).total_seconds() * 1000)
    logger = EventLogger(log_path, request_id=new_request_id())
    log_schedule_due(
        logger,
        schedule_id=record.schedule_id,
        skill_id=record.skill_id,
        run_at=_format_schedule_time(record.run_at),
        due_at=_format_schedule_time(due_at),
        lag_ms=lag_ms,
        retries=record.retries,
        max_retries=record.max_retries,
    )
    start = time.perf_counter()
    log_schedule_started(
        logger,
        schedule_id=record.schedule_id,
        skill_id=record.skill_id,
        run_at=_format_schedule_time(record.run_at),
        due_at=_format_schedule_time(due_at),
        lag_ms=lag_ms,
        retries=record.retries,
        max_retries=record.max_retries,
    )

    internal_skill_id = to_internal_id(record.skill_id)
    plan = build_execution_plan(
        to_public_id(internal_skill_id),
        internal_skill_id,
        record.payload,
    )
    try:
        result = orchestrator.execute_plan(
            plan,
            execute=True,
            dry_run=False,
            approval=record.approval_status,
            approval_token=record.approval_token,
            role=record.role,
            attributes=None,
            plan_path=None,
            debug_trace=None,
            logger=logger,
            request_start=start,
        )
    except Exception as exc:  # pragma: no cover - click handles display
        duration_ms = (time.perf_counter() - start) * 1000
        record.mark_failure(now, exc.__class__.__name__)
        log_schedule_failed(
            logger,
            schedule_id=record.schedule_id,
            skill_id=record.skill_id,
            duration_ms=duration_ms,
            error_class=exc.__class__.__name__,
            retries=record.retries,
            max_retries=record.max_retries,
        )
        return False, exc.__class__.__name__

    duration_ms = (time.perf_counter() - start) * 1000
    status = result.get("status")
    if status == "success":
        record.mark_success(now)
        log_schedule_completed(
            logger,
            schedule_id=record.schedule_id,
            skill_id=record.skill_id,
            duration_ms=duration_ms,
            status="success",
            retries=record.retries,
            max_retries=record.max_retries,
        )
        return True, None

    reason = result.get("reason") or result.get("policy_id") or "execution_failed"
    record.mark_failure(now, reason)
    log_schedule_failed(
        logger,
        schedule_id=record.schedule_id,
        skill_id=record.skill_id,
        duration_ms=duration_ms,
        error_class=reason,
        retries=record.retries,
        max_retries=record.max_retries,
    )
    return False, reason


# Command Groups
@click.group("secrets")
def secrets() -> None:
    """Manage connector secrets."""

@secrets.command("init")
@click.option("--connector", "connector_id", required=True)
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
def secrets_init(connector_id: str, root_path: Path) -> None:
    """Initialize connector secrets in an env file."""
    try:
        prompts = build_secret_prompts(connector_id, root_path)
    except ConnectorNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    if not prompts:
        click.echo("no_secrets_required")
        return

    click.echo(
        f"required_secrets: {', '.join(prompt.key for prompt in prompts)}"
    )
    values: dict[str, str] = {}
    for prompt in prompts:
        values[prompt.env_key] = click.prompt(prompt.prompt, hide_input=True)

    secrets_file = default_secrets_path(root_path)
    update_secrets_file(secrets_file, values)
    update_env_example(Path.cwd() / ".env.example", values.keys())
    click.echo(f"secrets_written: {secrets_file}")


@click.group("suggestions")
def suggestions() -> None:
    """Run proactive suggestion workflows."""

@suggestions.command("run")
@click.option(
    "--context",
    "context_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
)
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
@click.option("--relevance-window-hours", type=int, default=24, show_default=True)
def suggestions_run(
    context_path: Path | None, root_path: Path, relevance_window_hours: int
) -> None:
    """Generate proactive suggestions from context signals."""
    monitor = ContextMonitor(relevance_window_hours=relevance_window_hours)
    path = context_path or (Path(root_path) / "suggestions" / "context.json")
    try:
        signals = load_context_signals(path)
    except ContextMonitorError as exc:
        raise click.ClickException(str(exc)) from exc
    scheduler = SuggestionScheduler(
        monitor,
        suggestion_store_from_env(root_path),
        preferences_store_from_env(root_path),
    )
    suggestions = scheduler.run(signals)
    if not suggestions:
        click.echo("no_suggestions")
        return
    for suggestion in suggestions:
        click.echo(f"suggestion_created: {suggestion.suggestion_id}")

@suggestions.command("dismiss")
@click.argument("suggestion_id")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
def suggestions_dismiss(suggestion_id: str, root_path: Path) -> None:
    """Dismiss a suggestion and reduce future frequency."""
    notifier = NotificationCenter(
        suggestion_store_from_env(root_path),
        preferences_store_from_env(root_path),
    )
    dismissed = notifier.dismiss(suggestion_id)
    if dismissed is None:
        raise click.ClickException("suggestion_not_found")
    click.echo(f"suggestion_dismissed: {dismissed.suggestion_id}")


@click.group("schedule")
def schedule() -> None:
    """Manage scheduled skill execution."""

@schedule.command("add")
@click.argument("skill_id")
@click.option("--run-at", required=True)
@click.option("--timezone", default=None)
@click.option("--payload", default="ok", show_default=True)
@click.option("--enabled/--disabled", default=True, show_default=True)
@click.option("--max-retries", type=int, default=0, show_default=True)
@click.option("--role", default=None)
@click.option(
    "--approval",
    type=click.Choice(["approved", "denied"], case_sensitive=False),
    default=None,
)
@click.option("--approval-token", default=None)
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
def schedule_add(
    skill_id: str,
    run_at: str,
    timezone: str | None,
    payload: str,
    enabled: bool,
    max_retries: int,
    role: str | None,
    approval: str | None,
    approval_token: str | None,
    root_path: Path,
) -> None:
    """Add a scheduled skill execution."""
    if max_retries < 0:
        raise click.ClickException("max_retries must be >= 0")
    normalized_skill_id = to_internal_id(skill_id.strip())
    try:
        run_at_dt = parse_run_at(run_at, timezone)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    schedule_record = build_schedule(
        normalized_skill_id,
        run_at_dt,
        timezone=timezone,
        payload=payload,
        enabled=enabled,
        max_retries=max_retries,
        role=role,
        approval_status=approval.lower() if approval else None,
        approval_token=approval_token,
    )
    store = schedule_store_from_env(root_path)
    records = store.load()
    records.append(schedule_record)
    store.save(records)
    click.echo(f"schedule_added: {schedule_record.schedule_id}")


@schedule.command("list")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
def schedule_list(root_path: Path) -> None:
    """List saved schedules."""
    store = schedule_store_from_env(root_path)
    records = store.load()
    if not records:
        click.echo("no_schedules")
        return
    for record in records:
        due_at = record.due_at().isoformat()
        status = record.status
        enabled = "enabled" if record.enabled else "disabled"
        click.echo(
            f"{record.schedule_id} {record.skill_id} {due_at} {status} {enabled}"
        )


@schedule.command("enable")
@click.argument("schedule_id")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
def schedule_enable(schedule_id: str, root_path: Path) -> None:
    """Enable a schedule."""
    store = schedule_store_from_env(root_path)
    records = store.load()
    for record in records:
        if record.schedule_id == schedule_id:
            record.enabled = True
            store.save(records)
            click.echo(f"schedule_enabled: {schedule_id}")
            return
    raise click.ClickException("schedule_not_found")


@schedule.command("disable")
@click.argument("schedule_id")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
def schedule_disable(schedule_id: str, root_path: Path) -> None:
    """Disable a schedule."""
    store = schedule_store_from_env(root_path)
    records = store.load()
    for record in records:
        if record.schedule_id == schedule_id:
            record.enabled = False
            store.save(records)
            click.echo(f"schedule_disabled: {schedule_id}")
            return
    raise click.ClickException("schedule_not_found")


@schedule.command("remove")
@click.argument("schedule_id")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
def schedule_remove(schedule_id: str, root_path: Path) -> None:
    """Remove a schedule."""
    store = schedule_store_from_env(root_path)
    records = store.load()
    filtered = [record for record in records if record.schedule_id != schedule_id]
    if len(filtered) == len(records):
        raise click.ClickException("schedule_not_found")
    store.save(filtered)
    click.echo(f"schedule_removed: {schedule_id}")


@schedule.command("tick")
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
def schedule_tick(root_path: Path, log_path: Path | None) -> None:
    """Execute due schedules once."""
    store = schedule_store_from_env(root_path)
    records = store.load()
    if not records:
        click.echo("no_schedules")
        return
    due = due_schedules(records)
    if not due:
        click.echo("no_schedules_due")
        return
    log_destination = log_path or default_log_path(root_path)
    orchestrator = Orchestrator(root_path, log_destination)

    for record in sorted(due, key=lambda item: item.due_at()):
        success, _ = _execute_schedule(
            record,
            orchestrator=orchestrator,
            log_path=log_destination,
        )
        _emit_schedule_result(record, success)

    store.save(records)


@click.group("webhook")
def webhook() -> None:
    """Handle webhook triggers."""

@webhook.command("handle")
@click.option("--id", "trigger_id", required=True)
@click.option(
    "--path",
    "payload_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
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
@click.option("--signature", default=None)
@click.option("--idempotency-key", default=None)
def webhook_handle(
    trigger_id: str,
    payload_path: Path,
    root_path: Path,
    log_path: Path | None,
    signature: str | None,
    idempotency_key: str | None,
) -> None:
    """Handle a webhook payload and enqueue a job."""
    try:
        result = handle_webhook_event(
            trigger_id,
            payload_path,
            root_path,
            signature=signature,
            idempotency_key=idempotency_key,
            log_path=log_path,
        )
    except WebhookSignatureError as exc:
        raise click.ClickException(f"webhook_rejected: {exc.status_code}") from exc
    except WebhookPayloadError as exc:
        raise click.ClickException("webhook_rejected: 400") from exc
    except WebhookTriggerError as exc:
        raise click.ClickException(str(exc)) from exc

    if result.status == "skipped":
        click.echo("webhook_skipped")
        return
    if result.job_id:
        click.echo(f"webhook_enqueued: {result.job_id}")
        return
    click.echo("webhook_enqueued")


@click.group("job")
def job() -> None:
    """Manage async job execution."""

@job.command("enqueue")
@click.argument("skill_id")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
@click.option("--payload", default="ok", show_default=True)
@click.option("--max-retries", type=int, default=0, show_default=True)
@click.option(
    "--log-path",
    "log_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
)
def job_enqueue(
    skill_id: str,
    root_path: Path,
    payload: str,
    max_retries: int,
    log_path: Path | None,
) -> None:
    """Queue a job for async execution."""
    if max_retries < 0:
        raise click.ClickException("max_retries must be >= 0")
    normalized_skill_id = to_internal_id(skill_id.strip())
    store = job_store_from_env(root_path)
    record = store.enqueue(
        normalized_skill_id,
        payload=payload,
        max_retries=max_retries,
    )
    logger = EventLogger(log_path or default_log_path(root_path), request_id=new_request_id())
    log_job_enqueued(
        logger,
        job_id=record.job_id,
        skill_id=record.skill_id,
        status=record.status,
        max_retries=record.max_retries,
    )
    click.echo(f"job_enqueued: {record.job_id}")


@job.command("work")
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
@click.option("--limit", type=int, default=None)
def job_work(root_path: Path, log_path: Path | None, limit: int | None) -> None:
    """Process queued jobs once."""
    from skillos.jobs import JobWorker

    store = job_store_from_env(root_path)
    worker = JobWorker(root_path, store, log_path=log_path)
    results = worker.run_once(limit=limit)
    if not results:
        if store.list_all():
            click.echo("no_jobs_due")
        else:
            click.echo("no_jobs")
        return

    for job_record in results:
        _emit_job_result(job_record)

@click.command("add-connector")
@click.argument("connector_id")
@click.option(
    "--type",
    "connector_type",
    type=click.Choice(["http", "sql", "vector"], case_sensitive=False),
    default="http",
    show_default=True,
)
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
def add_connector(connector_id: str, connector_type: str, root_path: Path) -> None:
    """Scaffold a new connector definition."""
    try:
        from skillos.connectors import scaffold_connector
        
        connector_file = scaffold_connector(connector_id, root_path, connector_type)
    except (FileExistsError, ConnectorError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Created {connector_file}")

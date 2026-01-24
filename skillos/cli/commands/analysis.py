from __future__ import annotations
from pathlib import Path
import click

from skillos.skills.paths import default_skills_root
from skillos.telemetry import EventLogger, default_log_path, default_metrics_path, new_request_id
from skillos.feedback import (
    FeedbackTracker,
    feedback_store_from_env,
    normalize_skill_id,
)
from skillos.experimentation import ExperimentTracker, experiment_store_from_env
from skillos.optimizer import (
    Optimizer, 
    OptimizerConfig, 
    OptimizationLogger, 
    default_optimization_log_path
)
from skillos.skills.registry import SkillRegistry
from skillos.routing import build_router_from_env
from skillos.metrics import load_golden_queries, build_metrics_summary


def _parse_optimization_result(result: str) -> tuple[str, bool]:
    if ":" not in result:
        raise click.ClickException("Result must be in variant:outcome format")
    variant, outcome = result.split(":", 1)
    variant = variant.strip()
    outcome = outcome.strip().lower()
    if not variant:
        raise click.ClickException("Variant id is required")
    if outcome in {"success", "true", "1", "pass", "ok"}:
        return variant, True
    if outcome in {"failure", "false", "0", "fail"}:
        return variant, False
    raise click.ClickException(
        "Outcome must be success/failure or true/false"
    )

@click.command("feedback")
@click.argument("skill_id")
@click.option("--expected-skill-id", default=None)
@click.option("--source", default="cli", show_default=True)
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
def feedback(
    skill_id: str,
    expected_skill_id: str | None,
    source: str,
    root_path: Path,
    log_path: Path | None,
) -> None:
    """Record feedback to improve routing decisions."""
    tracker = FeedbackTracker(feedback_store_from_env(root_path))
    normalized_skill_id = normalize_skill_id(skill_id)
    normalized_expected = (
        normalize_skill_id(expected_skill_id)
        if expected_skill_id
        else normalized_skill_id
    )
    updates = tracker.record_correction(normalized_skill_id, normalized_expected)
    logger = EventLogger(log_path or default_log_path(root_path), request_id=new_request_id())
    logger.log(
        "feedback_received",
        expected_skill_id=normalized_expected,
        correction=normalized_expected != normalized_skill_id,
        source=source,
        skill_id=normalized_skill_id,
    )
    updated_skills = ", ".join(sorted(updates.keys()))
    click.echo(f"feedback_recorded: {updated_skills}")


@click.command("optimize")
@click.argument("skill_id")
@click.option("--variant", "variants", multiple=True, required=True)
@click.option("--baseline", "baseline_variant", default=None)
@click.option("--result", "results", multiple=True)
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
@click.option("--min-samples", type=int, default=5, show_default=True)
@click.option("--win-delta", type=float, default=0.1, show_default=True)
@click.option("--rollback-delta", type=float, default=0.1, show_default=True)
def optimize_skill(
    skill_id: str,
    variants: tuple[str, ...],
    baseline_variant: str | None,
    results: tuple[str, ...],
    root_path: Path,
    log_path: Path | None,
    min_samples: int,
    win_delta: float,
    rollback_delta: float,
) -> None:
    """Evaluate A/B experiment results and update active variant."""
    variant_list = [variant.strip() for variant in variants if variant.strip()]
    if len(variant_list) < 2:
        raise click.ClickException("At least two variants are required")
    store = experiment_store_from_env(root_path)
    tracker = ExperimentTracker(
        store,
        skill_id,
        variant_list,
        baseline_variant=baseline_variant,
    )

    for result in results:
        variant_id, success = _parse_optimization_result(result)
        if variant_id not in variant_list:
            raise click.ClickException(f"Unknown variant: {variant_id}")
        tracker.record_outcome(variant_id, success)

    config = OptimizerConfig(
        min_samples=min_samples,
        win_rate_delta=win_delta,
        rollback_delta=rollback_delta,
    )
    logger = OptimizationLogger(log_path or default_optimization_log_path(root_path))
    optimizer = Optimizer(store, logger, config)
    decision = optimizer.evaluate(skill_id)
    click.echo(f"optimization_decision: {decision.action}")


@click.command("metrics")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
@click.option(
    "--golden",
    "golden_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("tests/fixtures/golden_queries.json"),
    show_default=True,
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
)
def metrics_report(root_path: Path, golden_path: Path, output_path: Path | None) -> None:
    """Generate routing metrics from the golden query set."""
    registry = SkillRegistry(root_path)
    records = registry.load_all()
    feedback_tracker = FeedbackTracker(feedback_store_from_env(root_path))
    router = build_router_from_env(
        [record.metadata for record in records.values()],
        confidence_provider=feedback_tracker.get_confidence,
    )
    golden_queries = load_golden_queries(golden_path)
    summary = build_metrics_summary(router, golden_queries)

    destination = output_path or default_metrics_path(root_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(summary, encoding="utf-8")
    click.echo(f"metrics_written: {destination}")

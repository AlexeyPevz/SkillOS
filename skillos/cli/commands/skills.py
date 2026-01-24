from __future__ import annotations
from pathlib import Path
import click

from skillos.skills.paths import default_skills_root
from skillos.skills.registry import SkillRegistry
from skillos.skills.validation import validate_skills


@click.command("add-skill")
@click.argument("skill_id")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
def add_skill(skill_id: str, root_path: Path) -> None:
    """Scaffold a new skill."""
    try:
        from skillos.skills.scaffold import scaffold_skill
        from skillos.skills.errors import SkillValidationError

        metadata_file, implementation_file = scaffold_skill(skill_id, root_path)
    except (FileExistsError, SkillValidationError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Created {metadata_file} and {implementation_file}")


@click.command("deprecate-skill")
@click.argument("skill_id")
@click.option("--reason", default=None)
@click.option("--replacement", "replacement_id", default=None)
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
def deprecate_skill_command(
    skill_id: str,
    reason: str | None,
    replacement_id: str | None,
    root_path: Path,
) -> None:
    """Mark a skill as deprecated."""
    try:
        from skillos.skills.deprecation import deprecate_skill
        from skillos.skills.errors import SkillValidationError

        deprecate_skill(
            root_path,
            skill_id,
            reason=reason,
            replacement_id=replacement_id,
        )
    except (SkillValidationError, FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"skill_deprecated: {skill_id}")


@click.command("undeprecate-skill")
@click.argument("skill_id")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
def undeprecate_skill_command(skill_id: str, root_path: Path) -> None:
    """Remove deprecation flags from a skill."""
    try:
        from skillos.skills.deprecation import undeprecate_skill
        from skillos.skills.errors import SkillValidationError

        undeprecate_skill(root_path, skill_id)
    except (SkillValidationError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"skill_undeprecated: {skill_id}")


@click.command("validate")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
@click.option(
    "--check-entrypoints/--no-check-entrypoints",
    default=True,
    show_default=True,
)
def validate_command(root_path: Path, check_entrypoints: bool) -> None:
    """Validate all skills under the metadata directory."""
    # validate_skills is imported top-level but it's lightweight logic mostly
    # if it's heavy we can move import inside
    
    issues = validate_skills(root_path, check_entrypoints=check_entrypoints)
    if not issues:
        click.echo("validation_ok")
        return

    for issue in issues:
        skill_hint = issue.skill_id or "unknown"
        click.echo(
            f"invalid_skill: {skill_hint} {issue.category} "
            f"{issue.path} {issue.message}"
        )
    raise click.ClickException("validation_failed")

@click.command("run-skill")
@click.argument("skill_id")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
@click.option("--payload", default="ok", show_default=True)
def run_skill(skill_id: str, root_path: Path, payload: str) -> None:
    """Execute a skill implementation."""
    registry = SkillRegistry(root_path)
    registry.load_all()
    try:
        result = registry.execute(skill_id, payload=payload)
    except Exception as exc:  # pragma: no cover - click handles display
        raise click.ClickException(str(exc)) from exc

    click.echo(result)

@click.command("test")
@click.argument("skill_id")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
@click.option("--payload", default="ok", show_default=True)
@click.option(
    "--coverage-path",
    "coverage_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
)
def test_skill(
    skill_id: str,
    root_path: Path,
    payload: str,
    coverage_path: Path | None,
) -> None:
    """Run a local test for a skill and generate coverage."""
    try:
        from skillos.testing import run_skill_test

        result = run_skill_test(
            skill_id,
            root_path,
            payload=payload,
            coverage_path=coverage_path,
        )
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(result.output)
    click.echo(f"coverage_written: {result.coverage_path}")

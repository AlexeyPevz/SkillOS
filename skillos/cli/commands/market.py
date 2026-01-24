from __future__ import annotations
import json
from pathlib import Path
import click

from skillos.marketplace import (
    default_catalog_path,
    load_marketplace_catalog,
    get_package,
    install_package,
    uninstall_package,
    MarketplaceError,
    CatalogError,
)
from skillos.skills.paths import default_skills_root
from skillos.telemetry import EventLogger, default_log_path, new_request_id

@click.group("marketplace")
def marketplace() -> None:
    """Browse and install community skills."""

@marketplace.command("browse")
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=default_catalog_path(),
    show_default=True,
)
@click.option("--query", default=None)
@click.option("--tag", default=None)
def marketplace_browse(
    catalog_path: Path, query: str | None, tag: str | None
) -> None:
    """List packages from the marketplace catalog."""
    from skillos.marketplace import filter_packages  # keeping loose import if not used elsewhere, or move up
    
    try:
        packages = load_marketplace_catalog(catalog_path)
    except (CatalogError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc

    filtered = filter_packages(packages, query=query, tag=tag)
    if not filtered:
        click.echo("no_packages_found")
        return

    for package in filtered:
        click.echo(f"{package.id} {package.version} {package.name}")

@marketplace.command("show")
@click.argument("package_id")
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=default_catalog_path(),
    show_default=True,
)
def marketplace_show(package_id: str, catalog_path: Path) -> None:
    """Show details for a marketplace package."""
    try:
        packages = load_marketplace_catalog(catalog_path)
        package = get_package(packages, package_id)
    except (MarketplaceError, FileNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(json.dumps(package.model_dump(), indent=2, sort_keys=True))

@marketplace.command("install")
@click.argument("package_id")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=default_catalog_path(),
    show_default=True,
)
def marketplace_install(
    package_id: str, root_path: Path, catalog_path: Path
) -> None:
    """Install a marketplace package and dependencies."""
    logger = EventLogger(default_log_path(root_path), request_id=new_request_id())
    try:
        installed = install_package(
            package_id,
            root_path,
            catalog_path,
            logger=logger,
        )
    except MarketplaceError as exc:
        raise click.ClickException(str(exc)) from exc

    for pkg_id in installed:
        click.echo(f"installed: {pkg_id}")

@marketplace.command("uninstall")
@click.argument("package_id")
@click.option(
    "--root",
    "root_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=default_skills_root(),
    show_default=True,
)
@click.option("--prune/--no-prune", default=True, show_default=True)
def marketplace_uninstall(
    package_id: str, root_path: Path, prune: bool
) -> None:
    """Uninstall a marketplace package."""
    try:
        removed = uninstall_package(package_id, root_path, prune_orphans=prune)
    except MarketplaceError as exc:
        raise click.ClickException(str(exc)) from exc

    for pkg_id in removed:
        click.echo(f"removed: {pkg_id}")

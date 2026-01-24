from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
import yaml

from skillos.skills.models import SkillMetadata
from skillos.storage import atomic_write_text
from skillos.tenancy import resolve_tenant_root


DEFAULT_KEYRING: dict[str, str] = {"community-v1": "skillos-community-secret"}


class MarketplaceError(ValueError):
    pass


class CatalogError(MarketplaceError):
    pass


class PackageNotFoundError(MarketplaceError):
    pass


class DependencyResolutionError(MarketplaceError):
    pass


class SignatureVerificationError(MarketplaceError):
    pass


class PackageDependency(BaseModel):
    id: str
    version: str


class MarketplacePackage(BaseModel):
    id: str = Field(..., min_length=3)
    name: str
    description: str
    version: str
    entrypoint: str
    tags: list[str] = Field(default_factory=list)
    dependencies: list[PackageDependency] = Field(default_factory=list)
    implementation: str
    signature: str
    signature_key_id: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if "/" not in value or value.startswith("/") or value.endswith("/"):
            raise ValueError("id must be in 'domain/name' format")
        return value

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str) -> str:
        if ":" not in value:
            raise ValueError("entrypoint must be in 'module:function' format")
        return value

    @model_validator(mode="after")
    def validate_entrypoint_matches_id(self) -> "MarketplacePackage":
        domain, name = self.id.split("/", 1)
        module_path = self.entrypoint.split(":", 1)[0]
        expected = f"implementations.{domain}.{name}"
        if module_path != expected:
            raise ValueError("entrypoint module must match id")
        return self


def default_catalog_path() -> Path:
    return Path("marketplace/catalog.json")


def default_manifest_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "marketplace" / "installed.json"


def load_marketplace_catalog(path: Path) -> list[MarketplacePackage]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise CatalogError(f"Unable to read marketplace catalog: {exc}") from exc

    if not isinstance(raw, list):
        raise CatalogError("Marketplace catalog must be a list")

    packages: list[MarketplacePackage] = []
    for item in raw:
        try:
            packages.append(MarketplacePackage.model_validate(item))
        except ValidationError as exc:
            raise CatalogError(_format_validation_errors(exc)) from exc
    return packages


def filter_packages(
    packages: list[MarketplacePackage],
    *,
    query: str | None = None,
    tag: str | None = None,
) -> list[MarketplacePackage]:
    results: list[MarketplacePackage] = []
    query_lower = query.lower() if query else None
    for package in packages:
        if tag and tag not in package.tags:
            continue
        if query_lower:
            haystack = " ".join(
                [package.id, package.name, package.description, *package.tags]
            ).lower()
            if query_lower not in haystack:
                continue
        results.append(package)
    return results


def get_package(
    packages: list[MarketplacePackage], package_id: str
) -> MarketplacePackage:
    for package in packages:
        if package.id == package_id:
            return package
    raise PackageNotFoundError(f"Package not found: {package_id}")


def verify_signature(
    package: MarketplacePackage, keyring: dict[str, str] | None = None
) -> bool:
    keyring = keyring or DEFAULT_KEYRING
    secret = keyring.get(package.signature_key_id)
    if not secret:
        return False
    expected = compute_signature(package, secret)
    return hmac.compare_digest(package.signature, expected)


def ensure_signature(
    package: MarketplacePackage, keyring: dict[str, str] | None = None
) -> None:
    if not verify_signature(package, keyring=keyring):
        raise SignatureVerificationError(
            f"signature_verification_failed: {package.id}"
        )


def compute_signature(package: MarketplacePackage, secret: str) -> str:
    payload = json.dumps(
        _signature_payload(package),
        sort_keys=True,
        ensure_ascii=True,
    )
    digest = hashlib.sha256(f"{secret}:{payload}".encode("utf-8")).hexdigest()
    return digest


def resolve_install_plan(
    package_id: str, packages: list[MarketplacePackage]
) -> list[MarketplacePackage]:
    package_map = {package.id: package for package in packages}
    resolved: list[MarketplacePackage] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(current_id: str) -> None:
        if current_id in visited:
            return
        if current_id in visiting:
            raise DependencyResolutionError("circular_dependency")
        package = package_map.get(current_id)
        if not package:
            raise PackageNotFoundError(f"Package not found: {current_id}")
        visiting.add(current_id)
        for dependency in package.dependencies:
            dep_package = package_map.get(dependency.id)
            if not dep_package:
                raise DependencyResolutionError(
                    f"missing_dependency: {dependency.id}"
                )
            if not _version_satisfies(dependency.version, dep_package.version):
                raise DependencyResolutionError(
                    f"version_mismatch: {dependency.id}"
                )
            visit(dependency.id)
        visiting.remove(current_id)
        visited.add(current_id)
        resolved.append(package)

    visit(package_id)
    return resolved


def install_package(
    package_id: str,
    root: Path,
    catalog_path: Path,
    *,
    keyring: dict[str, str] | None = None,
    logger=None,
) -> list[str]:
    packages = load_marketplace_catalog(catalog_path)
    install_plan = resolve_install_plan(package_id, packages)
    manifest = load_install_manifest(default_manifest_path(root))

    for package in install_plan:
        try:
            ensure_signature(package, keyring=keyring)
        except SignatureVerificationError as exc:
            if logger:
                logger.log(
                    "marketplace_install_rejected",
                    package_id=package.id,
                    reason="invalid_signature",
                )
            raise exc

    for package in install_plan:
        _write_package_files(package, root)
        existing = manifest["packages"].get(package.id, {})
        is_explicit = existing.get("explicit", False) or package.id == package_id
        manifest["packages"][package.id] = {
            "version": package.version,
            "dependencies": [dep.id for dep in package.dependencies],
            "explicit": is_explicit,
        }

    save_install_manifest(default_manifest_path(root), manifest)
    return [package.id for package in install_plan]


def uninstall_package(
    package_id: str,
    root: Path,
    *,
    prune_orphans: bool = True,
) -> list[str]:
    manifest_path = default_manifest_path(root)
    manifest = load_install_manifest(manifest_path)
    if package_id not in manifest["packages"]:
        raise PackageNotFoundError(f"Package not installed: {package_id}")

    removed: set[str] = {package_id}
    del manifest["packages"][package_id]

    if prune_orphans:
        required = _required_packages(manifest)
        orphaned = set(manifest["packages"].keys()) - required
        for orphan_id in orphaned:
            removed.add(orphan_id)
            del manifest["packages"][orphan_id]

    for removed_id in removed:
        _remove_package_files(removed_id, root)

    save_install_manifest(manifest_path, manifest)
    return sorted(removed)


def load_install_manifest(path: Path) -> dict:
    if not path.exists():
        return {"packages": {}}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "packages" not in raw:
        raise CatalogError("Invalid marketplace manifest")
    if not isinstance(raw["packages"], dict):
        raise CatalogError("Invalid marketplace manifest")
    return raw


def save_install_manifest(path: Path, manifest: dict) -> None:
    atomic_write_text(
        path,
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


def _signature_payload(package: MarketplacePackage) -> dict:
    return {
        "id": package.id,
        "name": package.name,
        "description": package.description,
        "version": package.version,
        "entrypoint": package.entrypoint,
        "tags": package.tags,
        "dependencies": [dep.model_dump() for dep in package.dependencies],
        "implementation": package.implementation,
        "signature_key_id": package.signature_key_id,
    }


def _format_validation_errors(error: ValidationError) -> str:
    parts: list[str] = []
    for item in error.errors():
        loc = ".".join(str(piece) for piece in item.get("loc", [])) or "package"
        parts.append(f"{loc}: {item.get('msg')}")
    return "; ".join(parts)


def _version_satisfies(requirement: str, actual: str) -> bool:
    requirement = requirement.strip()
    if requirement.startswith(">="):
        return _version_tuple(actual) >= _version_tuple(requirement[2:])
    if requirement.startswith("=="):
        return actual == requirement[2:]
    return actual == requirement


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for segment in version.split("."):
        if segment.isdigit():
            parts.append(int(segment))
        else:
            break
    return tuple(parts)


def _write_package_files(package: MarketplacePackage, root: Path) -> None:
    metadata = SkillMetadata(
        id=package.id,
        name=package.name,
        description=package.description,
        version=package.version,
        entrypoint=package.entrypoint,
        tags=package.tags,
    )
    metadata_path, implementation_path = _package_paths(package, root)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_package_dir(implementation_path.parent)
    metadata_path.write_text(
        yaml.safe_dump(metadata.model_dump(), sort_keys=False),
        encoding="utf-8",
    )
    implementation_path.write_text(package.implementation, encoding="utf-8")


def _package_paths(
    package: MarketplacePackage, root: Path
) -> tuple[Path, Path]:
    domain, name = package.id.split("/", 1)
    metadata_path = Path(root) / "metadata" / domain / f"{name}.yaml"
    module_path = package.entrypoint.split(":", 1)[0]
    implementation_path = Path(root) / Path(*module_path.split(".")).with_suffix(
        ".py"
    )
    return metadata_path, implementation_path


def _remove_package_files(package_id: str, root: Path) -> None:
    domain, name = package_id.split("/", 1)
    metadata_path = Path(root) / "metadata" / domain / f"{name}.yaml"
    implementation_path = (
        Path(root) / "implementations" / domain / f"{name}.py"
    )
    if metadata_path.exists():
        metadata_path.unlink()
    if implementation_path.exists():
        implementation_path.unlink()
    _cleanup_dir(metadata_path.parent)
    _cleanup_dir(implementation_path.parent)


def _cleanup_dir(path: Path) -> None:
    if not path.exists():
        return
    try:
        next(path.iterdir())
    except StopIteration:
        path.rmdir()


def _ensure_package_dir(path: Path) -> None:
    root = path
    while root.name:
        root.mkdir(parents=True, exist_ok=True)
        init_file = root / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")
        if root.name == "implementations":
            break
        root = root.parent


def _required_packages(manifest: dict) -> set[str]:
    required: set[str] = set()
    explicit = [
        package_id
        for package_id, payload in manifest["packages"].items()
        if payload.get("explicit")
    ]

    def visit(package_id: str) -> None:
        if package_id in required:
            return
        required.add(package_id)
        for dep_id in manifest["packages"].get(package_id, {}).get(
            "dependencies", []
        ):
            if dep_id in manifest["packages"]:
                visit(dep_id)

    for package_id in explicit:
        visit(package_id)
    return required

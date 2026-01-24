from pathlib import Path

from skillos.telemetry import default_log_path
from skillos.tenancy import (
    normalize_tenant_id,
    resolve_tenant_root,
    tenant_id_from_env,
    tenant_id_from_path,
)


def test_normalize_tenant_id() -> None:
    assert normalize_tenant_id(None) is None
    assert normalize_tenant_id("   ") is None
    assert normalize_tenant_id("Acme Corp/42") == "Acme-Corp-42"


def test_tenant_id_from_env(monkeypatch) -> None:
    monkeypatch.setenv("SKILLOS_TENANT_ID", "  acme  ")
    assert tenant_id_from_env() == "acme"


def test_resolve_tenant_root_uses_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SKILLOS_TENANT_ID", "acme")
    root = tmp_path / "skills"
    assert resolve_tenant_root(root) == root / "tenants" / "acme"


def test_resolve_tenant_root_explicit_overrides_env(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SKILLOS_TENANT_ID", "acme")
    root = tmp_path / "skills"
    assert resolve_tenant_root(root, tenant_id="beta") == root / "tenants" / "beta"


def test_resolve_tenant_root_respects_existing_segment(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SKILLOS_TENANT_ID", "acme")
    root = tmp_path / "skills" / "tenants" / "acme"
    assert resolve_tenant_root(root) == root


def test_resolve_tenant_root_from_tenants_dir(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SKILLOS_TENANT_ID", "acme")
    root = tmp_path / "skills" / "tenants"
    assert resolve_tenant_root(root) == root / "acme"


def test_default_log_path_scoped_to_tenant(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SKILLOS_TENANT_ID", "acme")
    root = tmp_path / "skills"
    assert (
        default_log_path(root)
        == root / "tenants" / "acme" / "logs" / "execution.log"
    )


def test_tenant_id_from_path(tmp_path: Path) -> None:
    root = tmp_path / "skills" / "tenants" / "acme"
    assert tenant_id_from_path(root) == "acme"

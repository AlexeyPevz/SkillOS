from pathlib import Path

from skillos.marketplace import (
    default_manifest_path,
    install_package,
    load_install_manifest,
    uninstall_package,
)


def _catalog_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "marketplace"
        / "catalog.json"
    )


def test_install_uninstall_resolves_dependencies_and_versions(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    installed = install_package("community/hello", root, _catalog_path())
    assert installed == ["community/base", "community/hello"]

    manifest = load_install_manifest(default_manifest_path(root))
    assert set(manifest["packages"].keys()) == {"community/base", "community/hello"}
    assert manifest["packages"]["community/base"]["version"] == "1.0.0"
    assert manifest["packages"]["community/hello"]["dependencies"] == [
        "community/base"
    ]

    assert (root / "metadata" / "community" / "hello.yaml").exists()
    assert (root / "implementations" / "community" / "hello.py").exists()

    removed = uninstall_package("community/hello", root)
    assert set(removed) == {"community/base", "community/hello"}
    manifest = load_install_manifest(default_manifest_path(root))
    assert manifest["packages"] == {}
    assert not (root / "metadata" / "community" / "hello.yaml").exists()

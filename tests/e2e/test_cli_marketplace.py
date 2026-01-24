from pathlib import Path

from click.testing import CliRunner

from skillos.cli import cli


def _catalog_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "marketplace"
        / "catalog.json"
    )


def test_cli_marketplace_browse_install_and_execute() -> None:
    runner = CliRunner()
    catalog_path = _catalog_path()

    with runner.isolated_filesystem():
        root = Path("skills_root")
        browse_result = runner.invoke(
            cli,
            [
                "marketplace",
                "browse",
                "--catalog",
                str(catalog_path),
                "--tag",
                "greeting",
            ],
        )
        assert browse_result.exit_code == 0
        assert "community/hello" in browse_result.output
        assert "community/base" not in browse_result.output

        show_result = runner.invoke(
            cli,
            [
                "marketplace",
                "show",
                "community/hello",
                "--catalog",
                str(catalog_path),
            ],
        )
        assert show_result.exit_code == 0
        assert '"id": "community/hello"' in show_result.output

        install_result = runner.invoke(
            cli,
            [
                "marketplace",
                "install",
                "community/hello",
                "--root",
                str(root),
                "--catalog",
                str(catalog_path),
            ],
        )
        assert install_result.exit_code == 0
        assert "installed: community/hello" in install_result.output

        run_result = runner.invoke(
            cli,
            ["run-skill", "community/hello", "--root", str(root)],
        )
        assert run_result.exit_code == 0
        assert "hello-ok-base" in run_result.output

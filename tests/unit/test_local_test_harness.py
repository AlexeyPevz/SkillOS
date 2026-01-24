from pathlib import Path
import json

import httpx
import yaml

from skillos.testing import default_coverage_path, run_skill_test


def _write_external_api_skill(root: Path, skill_id: str) -> None:
    domain, name = skill_id.split("/", 1)
    metadata_dir = root / "metadata" / domain
    implementation_dir = root / "implementations" / domain
    metadata_dir.mkdir(parents=True, exist_ok=True)
    implementation_dir.mkdir(parents=True, exist_ok=True)

    for package_dir in [root / "implementations", implementation_dir]:
        init_file = package_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")

    metadata = {
        "id": skill_id,
        "name": "External Api",
        "description": "Calls an external API",
        "version": "0.1.0",
        "entrypoint": f"implementations.{domain}.{name}:run",
        "tags": [domain],
    }
    metadata_file = metadata_dir / f"{name}.yaml"
    metadata_file.write_text(
        yaml.safe_dump(metadata, sort_keys=False),
        encoding="utf-8",
    )

    implementation_file = implementation_dir / f"{name}.py"
    implementation_file.write_text(
        "import httpx\n\n"
        "def run(payload: str = \"ok\") -> str:\n"
        "    response = httpx.get(\"https://example.com/api\")\n"
        "    return response.json()[\"mocked\"]\n",
        encoding="utf-8",
    )


def test_run_skill_test_mocks_external_apis(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill_id = "demo/external_api"
    _write_external_api_skill(root, skill_id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"mocked": "local"})

    result = run_skill_test(skill_id, root, mock_handler=handler)

    assert result.output == "local"
    assert result.coverage_path == default_coverage_path(root, skill_id)
    assert result.coverage_path.exists()
    report = json.loads(result.coverage_path.read_text(encoding="utf-8"))
    assert report["skill_id"] == skill_id
    assert report["executed_lines"]

from pathlib import Path

import yaml

from skillos.skills.validation import validate_skills


def _ensure_package(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    init_file = path / "__init__.py"
    if not init_file.exists():
        init_file.write_text("", encoding="utf-8")


def _write_metadata(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def test_validate_skills_accepts_valid_entrypoint(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    metadata_file = root / "metadata" / "travel" / "search_flights.yaml"
    implementation_dir = root / "implementations" / "travel"
    _ensure_package(root / "implementations")
    _ensure_package(implementation_dir)
    implementation_file = implementation_dir / "search_flights.py"
    implementation_file.write_text(
        "def run(payload: str = 'ok') -> str:\n    return payload\n",
        encoding="utf-8",
    )
    _write_metadata(
        metadata_file,
        {
            "id": "travel/search_flights",
            "name": "Search Flights",
            "description": "Find flights",
            "version": "1.0.0",
            "entrypoint": "implementations.travel.search_flights:run",
            "tags": ["travel"],
        },
    )

    issues = validate_skills(root, check_entrypoints=True)
    assert issues == []


def test_validate_skills_reports_bad_entrypoint(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    metadata_file = root / "metadata" / "travel" / "missing.yaml"
    _write_metadata(
        metadata_file,
        {
            "id": "travel/missing",
            "name": "Missing",
            "description": "Missing implementation",
            "version": "1.0.0",
            "entrypoint": "implementations.travel.missing:run",
            "tags": ["travel"],
        },
    )

    issues = validate_skills(root, check_entrypoints=True)
    assert len(issues) == 1
    assert issues[0].category == "entrypoint"

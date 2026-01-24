from pathlib import Path

from skillos.skills.registry import SkillRegistry


def test_hot_reload_updates_registry(tmp_path):
    root = tmp_path / "skills"
    metadata_dir = root / "metadata" / "travel"
    metadata_dir.mkdir(parents=True)
    skill_file = metadata_dir / "search_flights.yaml"

    fixture_root = Path("tests/fixtures/skills")
    skill_file.write_text(
        (fixture_root / "valid_skill_v1.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    registry = SkillRegistry(root)
    registry.load_all()

    assert registry.get("travel/search_flights")
    assert registry.get("travel/search_flights").version == "1.0.0"
    assert registry.search("flights")

    skill_file.write_text(
        (fixture_root / "valid_skill_v2.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    registry.reload()
    assert registry.get("travel/search_flights").version == "1.1.0"

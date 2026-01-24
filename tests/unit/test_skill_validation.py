from pathlib import Path

import pytest

from skillos.skills.errors import SkillValidationError
from skillos.skills.loader import load_skill_file


def test_invalid_skill_yaml_reports_fields():
    fixture = Path("tests/fixtures/skills/invalid_missing_fields.yaml")
    with pytest.raises(SkillValidationError) as exc:
        load_skill_file(fixture)

    message = str(exc.value)
    assert "name" in message
    assert "entrypoint" in message
    assert "tags" in message


def test_invalid_version_reports_field() -> None:
    fixture = Path("tests/fixtures/skills/invalid_version.yaml")
    with pytest.raises(SkillValidationError) as exc:
        load_skill_file(fixture)

    message = str(exc.value)
    assert "version" in message

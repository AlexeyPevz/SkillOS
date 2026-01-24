import yaml
from fastapi.testclient import TestClient

from skillos.api import app


def test_api_validate_ok(skill_root, monkeypatch) -> None:
    monkeypatch.setenv("SKILLOS_ROOT", str(skill_root))
    client = TestClient(app)
    response = client.post("/validate", json={"check_entrypoints": False})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["issues"] == []


def test_api_deprecate_and_undeprecate(skill_root, monkeypatch) -> None:
    monkeypatch.setenv("SKILLOS_ROOT", str(skill_root))
    client = TestClient(app)
    response = client.post(
        "/skills/travel/search_flights/deprecate",
        json={"reason": "use travel/search_hotels"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["deprecated"] is True

    metadata_file = (
        skill_root / "metadata" / "travel" / "search_flights.yaml"
    )
    metadata = yaml.safe_load(metadata_file.read_text(encoding="utf-8"))
    assert metadata["deprecated"] is True
    assert metadata["deprecation_reason"] == "use travel/search_hotels"

    response = client.post(
        "/skills/travel/search_flights/undeprecate"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["deprecated"] is False

    metadata = yaml.safe_load(metadata_file.read_text(encoding="utf-8"))
    assert metadata.get("deprecated") is False
    assert "deprecation_reason" not in metadata

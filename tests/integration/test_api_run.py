import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from skillos.api import app
from skillos.policy_engine import default_policy_path


def test_api_health(tmp_path, monkeypatch) -> None:
    root = tmp_path / "skills"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SKILLOS_ROOT", str(root))
    monkeypatch.setenv("SKILLOS_STORAGE_BACKEND", "file")
    monkeypatch.delenv("SKILLOS_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SKILLOS_CACHE_ENABLED", "0")
    monkeypatch.delenv("SKILLOS_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_api_run_routes_query(skill_root, monkeypatch) -> None:
    monkeypatch.setenv("SKILLOS_ROOT", str(skill_root))
    client = TestClient(app)
    response = client.post(
        "/run",
        json={"query": "Find flights to Sochi", "execute": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "routed"
    assert payload["skill_id"] == "travel.search_flights"


def _ensure_package(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    init_file = path / "__init__.py"
    if not init_file.exists():
        init_file.write_text("", encoding="utf-8")


def _write_travel_impl(root: Path) -> None:
    impl_root = root / "implementations"
    impl_dir = impl_root / "travel"
    _ensure_package(impl_root)
    _ensure_package(impl_dir)
    (impl_dir / "search_flights.py").write_text(
        "def run(payload: str = 'ok') -> str:\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )


def _write_approval_policy(root: Path, requires_approval: bool) -> None:
    policy_path = default_policy_path(root)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        json.dumps(
            {
                "policies": [
                    {
                        "skill_id": "travel/search_flights",
                        "requires_approval": requires_approval,
                        "policy_id": "skill_policy",
                    }
                ]
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )


def test_api_reloads_approval_policy(skill_root, monkeypatch) -> None:
    from skillos import api as api_module

    api_module._ORCHESTRATOR_CACHE.clear()
    monkeypatch.setenv("SKILLOS_ROOT", str(skill_root))
    _write_travel_impl(skill_root)
    _write_approval_policy(skill_root, True)

    client = TestClient(app)
    response = client.post(
        "/run",
        json={"query": "Find flights to Sochi", "execute": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["policy_id"] == "approval_required"

    _write_approval_policy(skill_root, False)
    time.sleep(0.01)
    response = client.post(
        "/run",
        json={"query": "Find flights to Sochi", "execute": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["output"] == "ok"

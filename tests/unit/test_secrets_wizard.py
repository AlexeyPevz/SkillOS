from pathlib import Path

import yaml

from skillos.secrets_wizard import build_secret_prompts


def _write_connector(root: Path, payload: dict[str, object]) -> None:
    connectors_path = root / "connectors"
    connectors_path.mkdir(parents=True, exist_ok=True)
    connector_file = connectors_path / "weather.yaml"
    connector_file.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def test_build_secret_prompts_from_connector_schema(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_connector(
        root,
        {
            "id": "weather",
            "type": "http",
            "base_url": "https://api.example.com",
            "headers": {"X-Client": "skillos", "X-Api-Key": "secret:CLIENT_KEY"},
            "auth": {"type": "bearer", "token": "secret:API_TOKEN"},
        },
    )

    prompts = build_secret_prompts("weather", root)

    prompt_keys = {prompt.key for prompt in prompts}
    assert prompt_keys == {"API_TOKEN", "CLIENT_KEY"}
    env_keys = {prompt.env_key for prompt in prompts}
    assert env_keys == {
        "SKILLOS_WEATHER_API_TOKEN",
        "SKILLOS_WEATHER_CLIENT_KEY",
    }
    for prompt in prompts:
        assert prompt.key in prompt.prompt

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from skillos.connectors import build_secret_env_key, required_secrets_from_schema


@dataclass(frozen=True)
class SecretPrompt:
    key: str
    env_key: str
    prompt: str


def build_secret_prompts(connector_id: str, root: Path) -> list[SecretPrompt]:
    required = sorted(required_secrets_from_schema(root, connector_id))
    prompts: list[SecretPrompt] = []
    for key in required:
        env_key = build_secret_env_key(connector_id, key)
        prompt = f"Enter value for {key}"
        prompts.append(SecretPrompt(key=key, env_key=env_key, prompt=prompt))
    return prompts


def update_secrets_file(path: Path, values: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines: list[str] = []
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    updated_lines: list[str] = []
    seen_keys: set[str] = set()
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated_lines.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in values:
            updated_lines.append(f"{key}={values[key]}")
            seen_keys.add(key)
        else:
            updated_lines.append(line)
            seen_keys.add(key)

    for key in sorted(key for key in values if key not in seen_keys):
        updated_lines.append(f"{key}={values[key]}")

    path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def update_env_example(path: Path, keys: Iterable[str]) -> None:
    existing_lines: list[str] = []
    existing_keys: set[str] = set()
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8").splitlines()
        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            if key:
                existing_keys.add(key)

    updated_lines = list(existing_lines)
    for key in sorted(set(keys)):
        if key in existing_keys:
            continue
        updated_lines.append(f"{key}=changeme")

    if updated_lines != existing_lines or not path.exists():
        path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

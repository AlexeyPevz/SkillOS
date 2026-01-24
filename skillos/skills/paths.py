from pathlib import Path


def default_skills_root() -> Path:
    return Path(__file__).resolve().parent

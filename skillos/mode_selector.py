from __future__ import annotations

import re


_PIPELINE_SPLIT_RE = re.compile(r"\bthen\b|\bafter\b|->", re.IGNORECASE)
_PARALLEL_SPLIT_RE = re.compile(r"\band\b|&", re.IGNORECASE)


def select_mode(query: str) -> str:
    if _PIPELINE_SPLIT_RE.search(query):
        return "pipeline"
    if _PARALLEL_SPLIT_RE.search(query):
        return "parallel"
    return "single"


def split_query(query: str, mode: str) -> list[str]:
    normalized = (mode or "single").strip().lower()
    if normalized == "auto":
        normalized = select_mode(query)
    if normalized == "pipeline":
        parts = _PIPELINE_SPLIT_RE.split(query)
    elif normalized == "parallel":
        parts = _PARALLEL_SPLIT_RE.split(query)
    else:
        return [query.strip()] if query.strip() else []
    cleaned = [part.strip() for part in parts if part.strip()]
    return cleaned if len(cleaned) > 1 else [query.strip()] if query.strip() else []

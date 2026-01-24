from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable

from skillos.cache import CacheBackend, CacheConfig, cache_backend_from_env, cache_config_from_env
from skillos.routing import RoutingResult, SkillCandidate
from skillos.tenancy import tenant_id_from_path


@dataclass(frozen=True)
class RoutingCacheConfig:
    enabled: bool
    ttl_seconds: int
    prefix: str


class RoutingCache:
    def __init__(
        self,
        backend: CacheBackend,
        *,
        tenant_id: str,
        ttl_seconds: int,
        prefix: str,
    ) -> None:
        self._backend = backend
        self._tenant_id = tenant_id
        self._ttl_seconds = ttl_seconds
        self._prefix = prefix

    def get(self, query: str, tags: Iterable[str] | None = None) -> RoutingResult | None:
        key = self._key(query, tags)
        raw = self._backend.get(key)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return _routing_result_from_dict(payload)

    def set(
        self,
        query: str,
        tags: Iterable[str] | None,
        result: RoutingResult,
    ) -> None:
        key = self._key(query, tags)
        payload = json.dumps(
            _routing_result_to_dict(result),
            ensure_ascii=True,
        )
        self._backend.set(key, payload, self._ttl_seconds)

    def _key(self, query: str, tags: Iterable[str] | None) -> str:
        query_hash = _hash_text(query)
        tag_hash = _hash_tags(tags)
        return f"{self._prefix}:tenant:{self._tenant_id}:routing:{query_hash}:{tag_hash}"


def routing_cache_from_env(root_path) -> RoutingCache | None:
    config = cache_config_from_env()
    if not config.enabled:
        return None
    backend = cache_backend_from_env(config)
    if backend is None:
        return None
    tenant_id = tenant_id_from_path(root_path) or "default"
    routing_config = RoutingCacheConfig(
        enabled=config.enabled,
        ttl_seconds=config.ttl_seconds,
        prefix=config.prefix,
    )
    return RoutingCache(
        backend,
        tenant_id=tenant_id,
        ttl_seconds=routing_config.ttl_seconds,
        prefix=routing_config.prefix,
    )


def _routing_result_to_dict(result: RoutingResult) -> dict[str, object]:
    return {
        "status": result.status,
        "skill_id": result.skill_id,
        "internal_skill_id": result.internal_skill_id,
        "confidence": result.confidence,
        "alternatives": result.alternatives,
        "candidates": [
            {
                "skill_id": candidate.skill_id,
                "score": candidate.score,
                "keyword_score": candidate.keyword_score,
                "semantic_score": candidate.semantic_score,
                "internal_id": candidate.internal_id,
            }
            for candidate in result.candidates
        ],
    }


def _routing_result_from_dict(payload: dict[str, object]) -> RoutingResult | None:
    if not isinstance(payload, dict):
        return None
    candidates_raw = payload.get("candidates", [])
    candidates: list[SkillCandidate] = []
    if isinstance(candidates_raw, list):
        for item in candidates_raw:
            if not isinstance(item, dict):
                continue
            candidates.append(
                SkillCandidate(
                    skill_id=str(item.get("skill_id")),
                    score=float(item.get("score", 0.0)),
                    keyword_score=int(item.get("keyword_score", 0)),
                    semantic_score=float(item.get("semantic_score", 0.0)),
                    internal_id=item.get("internal_id"),
                )
            )
    return RoutingResult(
        status=str(payload.get("status")),
        skill_id=payload.get("skill_id"),
        internal_skill_id=payload.get("internal_skill_id"),
        confidence=float(payload.get("confidence", 0.0)),
        candidates=candidates,
        alternatives=[
            str(item) for item in payload.get("alternatives", []) if item is not None
        ],
    )


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_tags(tags: Iterable[str] | None) -> str:
    if not tags:
        return "none"
    normalized = sorted(tag.strip().lower() for tag in tags if tag.strip())
    if not normalized:
        return "none"
    return _hash_text(",".join(normalized))

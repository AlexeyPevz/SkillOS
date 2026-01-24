from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Callable, Iterable

from skillos.skills.models import SkillMetadata
from skillos.vector_search import (
    QdrantVectorSearch,
    VectorDocument,
    VectorSearchError,
    vector_search_config_from_env,
)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")

_KEYWORD_WEIGHTS: dict[str, int] = {
    "summarize": 3,
    "summary": 3,
    "summarise": 3,
    "convert": 3,
    "itinerary": 3,
    "quote": 3,
    "margin": 3,
    "exchange": 2,
    "rate": 2,
    "rates": 2,
    "logistics": 2,
    "shipping": 2,
    "delivery": 2,
    "hotel": 2,
    "hotels": 2,
    "flight": 2,
    "flights": 2,
    "tender": 2,
    "tenders": 2,
    "procurement": 2,
    "expenses": 2,
    "expense": 2,
    "web": 2,
    "search": 2,
    "document": 2,
    "requirements": 2,
    "certification": 2,
    "pricelist": 2,
    "price": 2,
    "prices": 2,
}


def to_public_id(skill_id: str) -> str:
    if "/" in skill_id:
        return skill_id.replace("/", ".", 1)
    return skill_id


def to_internal_id(skill_id: str) -> str:
    if "." in skill_id:
        return skill_id.replace(".", "/", 1)
    return skill_id


def _normalize_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in _TOKEN_RE.finditer(text.lower()):
        token = match.group(0)
        tokens.add(token)
        if token.endswith("ies") and len(token) > 4:
            tokens.add(f"{token[:-3]}y")
        elif token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
            tokens.add(token[:-1])
    return tokens


def _token_weight(token: str) -> int:
    return _KEYWORD_WEIGHTS.get(token, 1)


@dataclass(frozen=True)
class SkillProfile:
    internal_id: str
    public_id: str
    keywords: set[str]
    document: str
    tags: set[str]
    deprecated: bool

    @classmethod
    def from_metadata(cls, metadata: SkillMetadata) -> "SkillProfile":
        keywords: set[str] = set()
        document_parts: list[str] = []
        tags = _normalize_tag_filter(metadata.tags)
        for source in [
            metadata.id,
            metadata.name,
            metadata.description,
            *metadata.tags,
        ]:
            text = str(source)
            document_parts.append(text)
            keywords.update(_normalize_tokens(text))
        internal_id = metadata.id
        return cls(
            internal_id=internal_id,
            public_id=to_public_id(internal_id),
            keywords=keywords,
            document=" ".join(document_parts),
            tags=tags or set(),
            deprecated=metadata.deprecated,
        )


@dataclass
class SkillCandidate:
    skill_id: str
    score: float
    keyword_score: int = 0
    semantic_score: float = 0.0
    internal_id: str | None = None


@dataclass(frozen=True)
class RoutingConfig:
    mode: str = "hybrid"
    keyword_weight: float = 0.6
    vector_weight: float = 0.4
    vector_top_k: int = 8
    vector_min_score: float = 0.2
    include_deprecated: bool = False


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def routing_config_from_env() -> RoutingConfig:
    mode = os.getenv("SKILLOS_ROUTING_MODE", "hybrid").strip().lower()
    if mode not in {"keyword", "hybrid", "vector"}:
        mode = "keyword"
    vector_top_k = _env_int("SKILLOS_ROUTING_VECTOR_TOP_K", 8)
    vector_min_score = _env_float("SKILLOS_ROUTING_VECTOR_MIN_SCORE", 0.2)
    include_deprecated = _env_bool("SKILLOS_ROUTING_INCLUDE_DEPRECATED", False)
    if mode == "keyword":
        return RoutingConfig(
            mode=mode,
            keyword_weight=1.0,
            vector_weight=0.0,
            vector_top_k=vector_top_k,
            vector_min_score=vector_min_score,
            include_deprecated=include_deprecated,
        )
    if mode == "vector":
        return RoutingConfig(
            mode=mode,
            keyword_weight=0.0,
            vector_weight=1.0,
            vector_top_k=vector_top_k,
            vector_min_score=vector_min_score,
            include_deprecated=include_deprecated,
        )
    keyword_weight = _env_float("SKILLOS_ROUTING_KEYWORD_WEIGHT", 0.6)
    vector_weight = _env_float("SKILLOS_ROUTING_VECTOR_WEIGHT", 0.4)
    return RoutingConfig(
        mode=mode,
        keyword_weight=keyword_weight,
        vector_weight=vector_weight,
        vector_top_k=vector_top_k,
        vector_min_score=vector_min_score,
        include_deprecated=include_deprecated,
    )


@dataclass(frozen=True)
class RoutingResult:
    status: str
    skill_id: str | None
    internal_skill_id: str | None
    confidence: float
    candidates: list[SkillCandidate]
    alternatives: list[str]


class SkillRouter:
    def __init__(
        self,
        skills: Iterable[SkillMetadata],
        low_confidence_threshold: float = 0.25,
        margin_threshold: float = 0.05,
        confidence_provider: Callable[[str], float] | None = None,
        vector_search: QdrantVectorSearch | None = None,
        routing_config: RoutingConfig | None = None,
    ) -> None:
        profiles = [SkillProfile.from_metadata(metadata) for metadata in skills]
        self._profiles: dict[str, SkillProfile] = {
            profile.public_id: profile for profile in profiles
        }
        self._low_confidence_threshold = low_confidence_threshold
        self._margin_threshold = margin_threshold
        self._confidence_provider = confidence_provider
        self._vector_search = vector_search
        self._routing_config = routing_config or RoutingConfig()
        if self._vector_search:
            self._index_vector_search()

    def _adjust_score(self, score: float, skill_id: str) -> float:
        if not self._confidence_provider:
            return score
        confidence = self._confidence_provider(skill_id)
        multiplier = 1 + (confidence - 0.5) * 3
        if multiplier < 0.1:
            multiplier = 0.1
        elif multiplier > 2.0:
            multiplier = 2.0
        return score * multiplier

    def rank_candidates(
        self, query: str, candidates: Iterable[SkillCandidate]
    ) -> list[SkillCandidate]:
        query_tokens = _normalize_tokens(query)
        ranked: list[SkillCandidate] = []
        for candidate in candidates:
            public_id = to_public_id(candidate.skill_id)
            profile = self._profiles.get(public_id)
            keyword_score = candidate.keyword_score
            internal_id = candidate.internal_id
            if profile:
                if keyword_score == 0:
                    keyword_score = self._keyword_score(query_tokens, profile.keywords)
                if internal_id is None:
                    internal_id = profile.internal_id
            adjusted_score = self._adjust_score(candidate.score, public_id)
            ranked.append(
                SkillCandidate(
                    skill_id=public_id,
                    score=adjusted_score,
                    keyword_score=keyword_score,
                    semantic_score=candidate.semantic_score,
                    internal_id=internal_id,
                )
            )
        return sorted(
            ranked,
            key=lambda item: (-item.score, -item.keyword_score, item.skill_id),
        )

    def route(
        self,
        query: str,
        limit: int = 5,
        tags: Iterable[str] | None = None,
    ) -> RoutingResult:
        query_tokens = _normalize_tokens(query)
        keyword_candidates = self._keyword_candidates(query_tokens, tags)
        if not self._vector_search or self._routing_config.mode == "keyword":
            ranked = self.rank_candidates(query, keyword_candidates.values())[:limit]
            return self._build_result(ranked)

        semantic_scores = self._semantic_scores(query, tags)
        if not semantic_scores:
            ranked = self.rank_candidates(query, keyword_candidates.values())[:limit]
            return self._build_result(ranked)

        keyword_weight, vector_weight = self._normalized_weights(
            self._routing_config.keyword_weight,
            self._routing_config.vector_weight,
        )
        if vector_weight == 0.0:
            ranked = self.rank_candidates(query, keyword_candidates.values())[:limit]
            return self._build_result(ranked)

        candidates: list[SkillCandidate] = []
        for skill_id in set(keyword_candidates) | set(semantic_scores):
            keyword_candidate = keyword_candidates.get(skill_id)
            keyword_score = keyword_candidate.keyword_score if keyword_candidate else 0
            keyword_norm = keyword_candidate.score if keyword_candidate else 0.0
            semantic_score = semantic_scores.get(skill_id, 0.0)
            combined_score = (
                keyword_norm * keyword_weight + semantic_score * vector_weight
            )
            if combined_score <= 0.0:
                continue
            internal_id = (
                keyword_candidate.internal_id
                if keyword_candidate and keyword_candidate.internal_id
                else self._profiles[skill_id].internal_id
            )
            candidates.append(
                SkillCandidate(
                    skill_id=skill_id,
                    score=combined_score,
                    keyword_score=keyword_score,
                    semantic_score=semantic_score,
                    internal_id=internal_id,
                )
            )

        ranked = self.rank_candidates(query, candidates)[:limit]
        return self._build_result(ranked)

    def _build_result(self, ranked: list[SkillCandidate]) -> RoutingResult:
        if not ranked:
            return RoutingResult(
                status="no_skill_found",
                skill_id=None,
                internal_skill_id=None,
                confidence=0.0,
                candidates=[],
                alternatives=[],
            )

        top = ranked[0]
        confidence = top.score
        alternatives = [candidate.skill_id for candidate in ranked[1:3]]
        status = "selected"
        if confidence < self._low_confidence_threshold:
            status = "low_confidence"
        elif len(ranked) > 1 and (top.score - ranked[1].score) < self._margin_threshold:
            status = "low_confidence"

        return RoutingResult(
            status=status,
            skill_id=top.skill_id,
            internal_skill_id=top.internal_id,
            confidence=confidence,
            candidates=ranked,
            alternatives=alternatives,
        )

    @staticmethod
    def _keyword_score(query_tokens: set[str], keywords: set[str]) -> int:
        return sum(
            _token_weight(token) for token in query_tokens if token in keywords
        )

    def _keyword_candidates(
        self,
        query_tokens: set[str],
        tags: Iterable[str] | None = None,
    ) -> dict[str, SkillCandidate]:
        total_weight = sum(_token_weight(token) for token in query_tokens) or 1
        candidates: dict[str, SkillCandidate] = {}
        tag_filter = _normalize_tag_filter(tags)
        for profile in self._profiles.values():
            if not self._routing_config.include_deprecated and profile.deprecated:
                continue
            if tag_filter and not _matches_tags(profile.tags, tag_filter):
                continue
            keyword_score = self._keyword_score(query_tokens, profile.keywords)
            if keyword_score == 0:
                continue
            score = keyword_score / total_weight
            candidates[profile.public_id] = SkillCandidate(
                skill_id=profile.public_id,
                score=score,
                keyword_score=keyword_score,
                internal_id=profile.internal_id,
            )
        return candidates

    def _semantic_scores(
        self, query: str, tags: Iterable[str] | None = None
    ) -> dict[str, float]:
        if not self._vector_search:
            return {}
        try:
            matches = self._vector_search.search(
                query,
                limit=self._routing_config.vector_top_k,
                min_score=self._routing_config.vector_min_score,
            )
        except VectorSearchError:
            return {}
        scores: dict[str, float] = {}
        tag_filter = _normalize_tag_filter(tags)
        for match in matches:
            public_id = to_public_id(match.doc_id)
            if public_id not in self._profiles:
                continue
            profile = self._profiles[public_id]
            if (
                not self._routing_config.include_deprecated
                and profile.deprecated
            ):
                continue
            if tag_filter and not _matches_tags(
                profile.tags,
                tag_filter,
            ):
                continue
            scores[public_id] = match.score
        return scores

    def _normalized_weights(self, keyword_weight: float, vector_weight: float) -> tuple[float, float]:
        keyword_weight = max(0.0, keyword_weight)
        vector_weight = max(0.0, vector_weight)
        total = keyword_weight + vector_weight
        if total == 0.0:
            return 1.0, 0.0
        return keyword_weight / total, vector_weight / total

    def _index_vector_search(self) -> None:
        if not self._vector_search:
            return
        documents = [
            VectorDocument(
                doc_id=profile.public_id,
                text=profile.document,
                payload={"skill_id": profile.public_id},
            )
            for profile in self._profiles.values()
        ]
        try:
            self._vector_search.index(documents)
        except VectorSearchError:
            self._vector_search = None


def build_router_from_env(
    skills: Iterable[SkillMetadata],
    *,
    confidence_provider: Callable[[str], float] | None = None,
) -> SkillRouter:
    routing_config = routing_config_from_env()
    vector_search = None
    if routing_config.mode != "keyword":
        vector_config = vector_search_config_from_env()
        if vector_config:
            vector_search = QdrantVectorSearch(vector_config)
    return SkillRouter(
        skills,
        confidence_provider=confidence_provider,
        vector_search=vector_search,
        routing_config=routing_config,
    )


def _normalize_tag_filter(tags: Iterable[str] | None) -> set[str] | None:
    if not tags:
        return None
    normalized = {str(tag).strip().lower() for tag in tags if str(tag).strip()}
    return normalized or None


def _matches_tags(skill_tags: set[str], tag_filter: set[str]) -> bool:
    return bool(skill_tags.intersection(tag_filter))

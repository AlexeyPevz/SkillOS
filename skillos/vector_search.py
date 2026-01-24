from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
from typing import Iterable

import httpx


class VectorSearchError(ValueError):
    pass


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def _is_zero_vector(vector: list[float]) -> bool:
    return not any(vector)


def embed_text(text: str, dim: int) -> list[float]:
    if dim <= 0:
        raise VectorSearchError("embedding_dim must be positive")
    vector = [0.0 for _ in range(dim)]
    tokens = _tokenize(text)
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = -1.0 if (digest[4] & 1) else 1.0
        vector[index] += sign
    return _normalize_vector(vector)


@dataclass(frozen=True)
class VectorSearchConfig:
    base_url: str
    collection: str
    api_key: str | None = None
    embedding_dim: int = 128
    timeout_seconds: float = 5.0


def vector_search_config_from_env() -> VectorSearchConfig | None:
    base_url = os.getenv("SKILLOS_VECTOR_URL")
    if not base_url:
        return None
    collection = os.getenv("SKILLOS_VECTOR_COLLECTION", "skillos_skills")
    api_key = os.getenv("SKILLOS_VECTOR_API_KEY")
    embedding_dim = _env_int("SKILLOS_VECTOR_DIM", 128)
    timeout_seconds = _env_float("SKILLOS_VECTOR_TIMEOUT", 5.0)
    return VectorSearchConfig(
        base_url=base_url,
        collection=collection,
        api_key=api_key,
        embedding_dim=embedding_dim,
        timeout_seconds=timeout_seconds,
    )


@dataclass(frozen=True)
class VectorDocument:
    doc_id: str
    text: str
    payload: dict[str, object] | None = None


@dataclass(frozen=True)
class VectorMatch:
    doc_id: str
    score: float


class QdrantVectorSearch:
    def __init__(self, config: VectorSearchConfig) -> None:
        self._config = config
        self._base_url = config.base_url.rstrip("/")
        self._collection = config.collection

    def index(self, documents: Iterable[VectorDocument]) -> None:
        docs = list(documents)
        if not docs:
            return
        self._ensure_collection()
        points: list[dict[str, object]] = []
        for doc in docs:
            vector = embed_text(doc.text, self._config.embedding_dim)
            if _is_zero_vector(vector):
                continue
            payload = dict(doc.payload or {})
            if "skill_id" not in payload:
                payload["skill_id"] = doc.doc_id
            points.append(
                {
                    "id": doc.doc_id,
                    "vector": vector,
                    "payload": payload,
                }
            )
        if points:
            self._upsert(points)

    def search(
        self,
        query: str,
        *,
        limit: int,
        min_score: float | None = None,
    ) -> list[VectorMatch]:
        vector = embed_text(query, self._config.embedding_dim)
        if _is_zero_vector(vector):
            return []
        payload = {
            "vector": vector,
            "limit": limit,
            "with_payload": True,
        }
        data = self._request(
            "POST",
            f"/collections/{self._collection}/points/search",
            payload,
        )
        results = data.get("result", [])
        matches: list[VectorMatch] = []
        for item in results:
            try:
                score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            if min_score is not None and score < min_score:
                continue
            payload = item.get("payload") or {}
            doc_id = payload.get("skill_id", item.get("id"))
            if doc_id is None:
                continue
            matches.append(VectorMatch(doc_id=str(doc_id), score=score))
        return matches

    def _ensure_collection(self) -> None:
        url = f"{self._base_url}/collections/{self._collection}"
        response = self._send("GET", url, None)
        if response.status_code == 404:
            payload = {
                "vectors": {"size": self._config.embedding_dim, "distance": "Cosine"}
            }
            self._request("PUT", f"/collections/{self._collection}", payload)
            return
        if not response.is_success:
            raise VectorSearchError(
                f"vector_search_error: {response.status_code}"
            )

    def _upsert(self, points: list[dict[str, object]]) -> None:
        payload = {"points": points}
        self._request(
            "PUT",
            f"/collections/{self._collection}/points?wait=true",
            payload,
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None,
    ) -> dict[str, object]:
        url = f"{self._base_url}{path}"
        response = self._send(method, url, payload)
        if not response.is_success:
            raise VectorSearchError(
                f"vector_search_error: {response.status_code}"
            )
        if not response.content:
            return {}
        return response.json()

    def _send(
        self,
        method: str,
        url: str,
        payload: dict[str, object] | None,
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if self._config.api_key:
            headers["api-key"] = self._config.api_key
        try:
            return httpx.request(
                method,
                url,
                headers=headers or None,
                json=payload,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise VectorSearchError("vector_search_unavailable") from exc

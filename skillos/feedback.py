from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path

from skillos.storage import atomic_write_text
from skillos.tenancy import resolve_tenant_root
from skillos.storage_backend import (
    pg_connect,
    require_postgres_dsn,
    resolve_tenant_id,
    storage_backend_from_env,
)

DEFAULT_CONFIDENCE = 0.5


def default_feedback_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "feedback" / "confidence.json"


def normalize_skill_id(skill_id: str) -> str:
    if "/" in skill_id:
        return skill_id.replace("/", ".", 1)
    return skill_id


class FeedbackOutcome(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


@dataclass
class FeedbackRecord:
    confidence: float
    positive: int = 0
    negative: int = 0


class FeedbackStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, FeedbackRecord]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        skills = raw.get("skills", raw)
        records: dict[str, FeedbackRecord] = {}
        for skill_id, payload in skills.items():
            records[skill_id] = FeedbackRecord(
                confidence=float(payload.get("confidence", DEFAULT_CONFIDENCE)),
                positive=int(payload.get("positive", 0)),
                negative=int(payload.get("negative", 0)),
            )
        return records

    def save(self, records: dict[str, FeedbackRecord]) -> None:
        payload = {
            "skills": {
                skill_id: {
                    "confidence": record.confidence,
                    "positive": record.positive,
                    "negative": record.negative,
                }
                for skill_id, record in records.items()
            }
        }
        atomic_write_text(
            self.path,
            json.dumps(payload, ensure_ascii=True),
            encoding="utf-8",
        )


class FeedbackStorePostgres:
    def __init__(self, dsn: str, *, tenant_id: str, schema: str = "skillos") -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._schema = schema
        self._ensure_table()

    def load(self) -> dict[str, FeedbackRecord]:
        query = (
            f"SELECT skill_id, confidence, positive, negative "
            f"FROM {self._schema}.feedback WHERE tenant_id = %s"
        )
        with pg_connect(self._dsn) as conn:
            rows = conn.execute(query, (self._tenant_id,)).fetchall()
        records: dict[str, FeedbackRecord] = {}
        for row in rows:
            skill_id = str(row.get("skill_id") or "")
            records[skill_id] = FeedbackRecord(
                confidence=float(row.get("confidence", DEFAULT_CONFIDENCE)),
                positive=int(row.get("positive", 0)),
                negative=int(row.get("negative", 0)),
            )
        return records

    def save(self, records: dict[str, FeedbackRecord]) -> None:
        with pg_connect(self._dsn) as conn:
            for skill_id, record in records.items():
                conn.execute(
                    f"""
                    INSERT INTO {self._schema}.feedback
                        (tenant_id, skill_id, confidence, positive, negative)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, skill_id) DO UPDATE SET
                        confidence = EXCLUDED.confidence,
                        positive = EXCLUDED.positive,
                        negative = EXCLUDED.negative,
                        updated_at = now()
                    """,
                    (
                        self._tenant_id,
                        skill_id,
                        record.confidence,
                        record.positive,
                        record.negative,
                    ),
                )

    def _ensure_table(self) -> None:
        with pg_connect(self._dsn) as conn:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._schema}.feedback (
                    tenant_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    confidence DOUBLE PRECISION NOT NULL,
                    positive INTEGER NOT NULL,
                    negative INTEGER NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (tenant_id, skill_id)
                )
                """
            )


def feedback_store_from_env(root: Path) -> FeedbackStore | FeedbackStorePostgres:
    config = storage_backend_from_env()
    if config.backend != "postgres":
        return FeedbackStore(default_feedback_path(root))
    dsn = require_postgres_dsn(config, context="feedback")
    tenant_id = resolve_tenant_id(Path(root))
    return FeedbackStorePostgres(
        dsn,
        tenant_id=tenant_id,
        schema=config.postgres_schema,
    )


class FeedbackTracker:
    def __init__(self, store: FeedbackStore, default_confidence: float = DEFAULT_CONFIDENCE) -> None:
        self._store = store
        self._default_confidence = default_confidence

    def get_confidence(self, skill_id: str) -> float:
        normalized = normalize_skill_id(skill_id)
        record = self._store.load().get(normalized)
        if record:
            return record.confidence
        return self._default_confidence

    def record_feedback(self, skill_id: str, outcome: FeedbackOutcome) -> FeedbackRecord:
        normalized = normalize_skill_id(skill_id)
        records = self._store.load()
        record = records.get(
            normalized,
            FeedbackRecord(confidence=self._default_confidence),
        )
        if outcome == FeedbackOutcome.POSITIVE:
            record.positive += 1
            record.confidence = record.confidence + (1 - record.confidence) * 0.1
        else:
            record.negative += 1
            record.confidence = record.confidence * 0.9
        records[normalized] = record
        self._store.save(records)
        return record

    def record_correction(
        self, selected_skill_id: str, expected_skill_id: str | None
    ) -> dict[str, FeedbackRecord]:
        normalized_selected = normalize_skill_id(selected_skill_id)
        normalized_expected = (
            normalize_skill_id(expected_skill_id)
            if expected_skill_id
            else normalized_selected
        )
        updates: dict[str, FeedbackRecord] = {}
        if normalized_selected == normalized_expected:
            updates[normalized_selected] = self.record_feedback(
                normalized_selected, FeedbackOutcome.POSITIVE
            )
        else:
            updates[normalized_selected] = self.record_feedback(
                normalized_selected, FeedbackOutcome.NEGATIVE
            )
            updates[normalized_expected] = self.record_feedback(
                normalized_expected, FeedbackOutcome.POSITIVE
            )
        return updates

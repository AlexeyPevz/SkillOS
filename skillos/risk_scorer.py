from __future__ import annotations

from dataclasses import dataclass
import re

HIGH_RISK_THRESHOLD = 11
CRITICAL_RISK_THRESHOLD = 16
MEDIUM_RISK_THRESHOLD = 6
_HIGH_RISK_SCORE = 12
_LOW_RISK_SCORE = 2

_HIGH_RISK_PATTERNS: dict[str, re.Pattern[str]] = {
    "delete": re.compile(r"\bdelete\b"),
    "remove": re.compile(r"\bremove\b"),
    "drop": re.compile(r"\bdrop\b"),
    "bulk_update": re.compile(r"\bbulk[-\s]+update\b"),
    "update_all": re.compile(r"\bupdate\s+all\b"),
    "mass_update": re.compile(r"\bmass\s+update\b"),
}


@dataclass(frozen=True)
class RiskAssessment:
    score: int
    level: str
    reasons: list[str]


class RiskScorer:
    def __init__(
        self,
        high_risk_threshold: int = HIGH_RISK_THRESHOLD,
        critical_risk_threshold: int = CRITICAL_RISK_THRESHOLD,
    ) -> None:
        self._high_risk_threshold = high_risk_threshold
        self._critical_risk_threshold = critical_risk_threshold

    def assess(self, text: str, skill_id: str | None = None) -> RiskAssessment:
        combined = " ".join(part for part in [text, skill_id] if part)
        normalized = combined.lower()
        reasons = [
            name for name, pattern in _HIGH_RISK_PATTERNS.items() if pattern.search(normalized)
        ]
        score = _HIGH_RISK_SCORE if reasons else _LOW_RISK_SCORE
        level = self._level_for(score)
        return RiskAssessment(score=score, level=level, reasons=reasons)

    def _level_for(self, score: int) -> str:
        if score >= self._critical_risk_threshold:
            return "critical"
        if score >= self._high_risk_threshold:
            return "high"
        if score >= MEDIUM_RISK_THRESHOLD:
            return "medium"
        return "low"

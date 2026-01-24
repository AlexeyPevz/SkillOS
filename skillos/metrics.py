from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Iterable

from skillos.budget import budget_config_from_env
from skillos.routing import SkillRouter
from skillos.telemetry import token_count


def load_golden_queries(path: Path) -> list[dict[str, object]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int(round((percentile / 100) * (len(sorted_values) - 1)))
    return sorted_values[index]


def _mean(values: Iterable[float]) -> float:
    values_list = list(values)
    if not values_list:
        return 0.0
    return sum(values_list) / len(values_list)


def build_metrics_summary(router: SkillRouter, golden_queries: list[dict[str, object]]) -> str:
    total_requests = len(golden_queries)
    if total_requests == 0:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_requests": 0,
            "metrics": {},
        }
        return json.dumps(payload, ensure_ascii=True, indent=2)

    budget_config = budget_config_from_env()

    correct = 0
    top3 = 0
    no_skill_found = 0
    override_rate = 0.0

    routing_latencies: list[float] = []
    request_latencies: list[float] = []
    confidences: list[float] = []
    outcomes: list[float] = []

    tokens_total = 0
    cost_total = 0.0
    skill_totals: dict[str, int] = {}
    skill_success: dict[str, int] = {}
    error_counts: dict[str, int] = {}

    for item in golden_queries:
        query = str(item["query"])
        expected_skill = str(item["expected_skill_id"])
        tokens_total += token_count(query)
        cost_total += budget_config.standard_cost

        start = time.perf_counter()
        result = router.route(query)
        routing_latency = (time.perf_counter() - start) * 1000
        routing_latencies.append(routing_latency)
        request_latencies.append(routing_latency)

        predicted_skill = result.skill_id
        is_correct = predicted_skill == expected_skill
        if is_correct:
            correct += 1
        top3_candidates = [candidate.skill_id for candidate in result.candidates[:3]]
        if expected_skill in top3_candidates:
            top3 += 1
        if result.status == "no_skill_found":
            no_skill_found += 1

        confidences.append(result.confidence)
        outcomes.append(1.0 if is_correct else 0.0)

        skill_totals[expected_skill] = skill_totals.get(expected_skill, 0) + 1
        if is_correct:
            skill_success[expected_skill] = skill_success.get(expected_skill, 0) + 1

        error_class = None
        if result.status == "no_skill_found":
            error_class = "no_skill_found"
        elif not is_correct:
            error_class = "misroute"
        if error_class:
            error_counts[error_class] = error_counts.get(error_class, 0) + 1

    skill_success_rate = {
        skill_id: skill_success.get(skill_id, 0) / total
        for skill_id, total in skill_totals.items()
    }
    error_rate_by_class = {
        error_class: count / total_requests
        for error_class, count in error_counts.items()
    }

    brier_scores = [
        (confidence - outcome) ** 2
        for confidence, outcome in zip(confidences, outcomes)
    ]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_requests": total_requests,
        "metrics": {
            "routing_top1_accuracy": correct / total_requests,
            "routing_top3_accuracy": top3 / total_requests,
            "routing_no_skill_found_rate": no_skill_found / total_requests,
            "routing_override_rate": override_rate,
            "routing_confidence_brier": _mean(brier_scores),
            "routing_p95_ms": _percentile(routing_latencies, 95),
            "request_p95_ms": _percentile(request_latencies, 95),
            "skill_success_rate": skill_success_rate,
            "error_rate_by_class": error_rate_by_class,
            "tokens_per_request": tokens_total / total_requests,
            "cost_per_request": cost_total / total_requests,
        },
    }
    return json.dumps(payload, ensure_ascii=True, indent=2)

import json
from pathlib import Path
import time

from skillos.routing import SkillRouter
from skillos.skills.registry import SkillRegistry


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int(round((percentile / 100) * (len(sorted_values) - 1)))
    return sorted_values[index]


def test_routing_latency_p95(skill_root):
    registry = SkillRegistry(skill_root)
    records = registry.load_all()
    router = SkillRouter([record.metadata for record in records.values()])

    golden_queries = json.loads(
        Path("tests/fixtures/golden_queries.json").read_text(encoding="utf-8")
    )

    timings_ms: list[float] = []
    for item in golden_queries:
        start = time.perf_counter()
        router.route(item["query"])
        duration_ms = (time.perf_counter() - start) * 1000
        timings_ms.append(duration_ms)

    p95 = _percentile(timings_ms, 95)
    assert p95 <= 100

import json
from pathlib import Path

from skillos.routing import SkillRouter
from skillos.skills.registry import SkillRegistry


def test_golden_queries_accuracy(skill_root):
    registry = SkillRegistry(skill_root)
    records = registry.load_all()
    router = SkillRouter([record.metadata for record in records.values()])

    golden_queries = json.loads(
        Path("tests/fixtures/golden_queries.json").read_text(encoding="utf-8")
    )

    correct = 0
    for item in golden_queries:
        result = router.route(item["query"])
        if result.skill_id == item["expected_skill_id"]:
            correct += 1
    accuracy = correct / len(golden_queries)
    assert accuracy >= 0.80

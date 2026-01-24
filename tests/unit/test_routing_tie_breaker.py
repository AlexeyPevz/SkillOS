import json
from pathlib import Path

from skillos.routing import SkillCandidate, SkillRouter
from skillos.skills.models import SkillMetadata


def test_deterministic_ranking_ties(skill_catalog):
    skills = [SkillMetadata.model_validate(item) for item in skill_catalog]
    router = SkillRouter(skills)

    fixtures = json.loads(
        Path("tests/fixtures/queries/keyword_ties.json").read_text(encoding="utf-8")
    )

    for item in fixtures:
        candidates = [
            SkillCandidate(skill_id=entry["skill_id"], score=entry["score"])
            for entry in item["candidates"]
        ]
        ranked = router.rank_candidates(item["query"], candidates)
        assert [candidate.skill_id for candidate in ranked] == item["expected_order"]

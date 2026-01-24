from pathlib import Path

from skillos.feedback import FeedbackOutcome, FeedbackStore, FeedbackTracker
from skillos.routing import SkillRouter
from skillos.skills.models import SkillMetadata


def _sample_skills() -> list[SkillMetadata]:
    return [
        SkillMetadata(
            id="sales/alpha_report",
            name="Alpha Report",
            description="Summarize sales reports.",
            version="1.0.0",
            entrypoint="sales.alpha:run",
            tags=["summary", "report"],
        ),
        SkillMetadata(
            id="sales/beta_report",
            name="Beta Report",
            description="Summarize sales reports.",
            version="1.0.0",
            entrypoint="sales.beta:run",
            tags=["summary", "report"],
        ),
    ]


def test_feedback_updates_confidence_and_demotes_rank(tmp_path: Path) -> None:
    skills = _sample_skills()
    query = "Report summary"

    baseline_router = SkillRouter(skills)
    baseline = baseline_router.route(query)
    assert baseline.skill_id == "sales.alpha_report"

    store = FeedbackStore(tmp_path / "confidence.json")
    tracker = FeedbackTracker(store)
    before = tracker.get_confidence("sales.alpha_report")

    tracker.record_feedback("sales.alpha_report", FeedbackOutcome.NEGATIVE)
    after = tracker.get_confidence("sales.alpha_report")

    assert after < before

    router = SkillRouter(skills, confidence_provider=tracker.get_confidence)
    result = router.route(query)
    assert result.skill_id == "sales.beta_report"

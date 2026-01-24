from skillos.feedback import FeedbackOutcome, FeedbackStore, FeedbackTracker, default_feedback_path
from skillos.routing import SkillRouter
from skillos.skills.registry import SkillRegistry


def test_feedback_demotes_skill_in_routing(skill_root) -> None:
    registry = SkillRegistry(skill_root)
    records = registry.load_all()
    tracker = FeedbackTracker(FeedbackStore(default_feedback_path(skill_root)))
    router = SkillRouter(
        [record.metadata for record in records.values()],
        confidence_provider=tracker.get_confidence,
    )

    query = "Search travel itinerary options"
    baseline = router.route(query)
    assert baseline.skill_id == "travel.search_flights"

    for _ in range(3):
        tracker.record_feedback(baseline.skill_id, FeedbackOutcome.NEGATIVE)

    updated = router.route(query)
    assert updated.skill_id == "travel.build_itinerary"

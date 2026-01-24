from skillos.routing import SkillRouter
from skillos.skills.models import SkillMetadata


def test_routing_respects_tag_filter() -> None:
    skills = [
        SkillMetadata(
            id="travel/search_flights",
            name="Search Flights",
            description="Find flights",
            version="1.0.0",
            entrypoint="implementations.travel.search_flights:run",
            tags=["travel"],
        ),
        SkillMetadata(
            id="finance/convert_currency",
            name="Convert Currency",
            description="Convert money",
            version="1.0.0",
            entrypoint="implementations.finance.convert_currency:run",
            tags=["finance"],
        ),
    ]
    router = SkillRouter(skills)
    result = router.route("Find flights", tags=["travel"])
    assert result.skill_id == "travel.search_flights"


def test_routing_filters_out_unmatched_tags() -> None:
    skills = [
        SkillMetadata(
            id="travel/search_flights",
            name="Search Flights",
            description="Find flights",
            version="1.0.0",
            entrypoint="implementations.travel.search_flights:run",
            tags=["travel"],
        ),
    ]
    router = SkillRouter(skills)
    result = router.route("Find flights", tags=["finance"])
    assert result.status == "no_skill_found"

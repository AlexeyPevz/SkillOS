from skillos.routing import RoutingConfig, SkillRouter
from skillos.skills.models import SkillMetadata


def _sample_skills() -> list[SkillMetadata]:
    return [
        SkillMetadata(
            id="travel/search_flights",
            name="Search Flights",
            description="Find flights",
            version="1.0.0",
            entrypoint="implementations.travel.search_flights:run",
            tags=["travel"],
            deprecated=True,
            deprecation_reason="use travel/search_hotels",
            replacement_id="travel/search_hotels",
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


def test_routing_skips_deprecated_by_default() -> None:
    router = SkillRouter(
        _sample_skills(),
        routing_config=RoutingConfig(mode="keyword", include_deprecated=False),
    )
    result = router.route("Find flights")
    assert result.status == "no_skill_found"


def test_routing_can_include_deprecated() -> None:
    router = SkillRouter(
        _sample_skills(),
        routing_config=RoutingConfig(mode="keyword", include_deprecated=True),
    )
    result = router.route("Find flights")
    assert result.skill_id == "travel.search_flights"

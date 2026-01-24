from skillos.cache import MemoryCache
from skillos.routing import RoutingResult, SkillCandidate
from skillos.routing_cache import RoutingCache


def test_routing_cache_roundtrip() -> None:
    backend = MemoryCache()
    cache = RoutingCache(
        backend,
        tenant_id="acme",
        ttl_seconds=60,
        prefix="skillos",
    )
    result = RoutingResult(
        status="selected",
        skill_id="travel.search_flights",
        internal_skill_id="travel/search_flights",
        confidence=0.9,
        candidates=[
            SkillCandidate(
                skill_id="travel.search_flights",
                score=0.9,
                keyword_score=3,
                semantic_score=0.1,
                internal_id="travel/search_flights",
            )
        ],
        alternatives=[],
    )
    cache.set("Find flights", ["travel"], result)
    cached = cache.get("Find flights", ["travel"])
    assert cached is not None
    assert cached.skill_id == result.skill_id
    assert cached.candidates[0].skill_id == result.candidates[0].skill_id


def test_routing_cache_isolated_by_tenant() -> None:
    backend = MemoryCache()
    cache_a = RoutingCache(
        backend,
        tenant_id="acme",
        ttl_seconds=60,
        prefix="skillos",
    )
    cache_b = RoutingCache(
        backend,
        tenant_id="beta",
        ttl_seconds=60,
        prefix="skillos",
    )
    result = RoutingResult(
        status="selected",
        skill_id="travel.search_flights",
        internal_skill_id="travel/search_flights",
        confidence=0.9,
        candidates=[],
        alternatives=[],
    )
    cache_a.set("Find flights", None, result)
    assert cache_b.get("Find flights", None) is None

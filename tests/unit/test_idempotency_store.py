from datetime import datetime, timedelta, timezone

from skillos.idempotency import IdempotencyStore


def test_idempotency_store_detects_duplicates_and_expiry(tmp_path) -> None:
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    current = [base_time]

    def now_provider() -> datetime:
        return current[0]

    store = IdempotencyStore(tmp_path / "idempotency.json", now_provider=now_provider)

    first = store.check_and_record(
        "webhook",
        "ops/sample",
        "evt-1",
        ttl_seconds=60,
    )
    assert first.allowed is True

    duplicate = store.check_and_record(
        "webhook",
        "ops/sample",
        "evt-1",
        ttl_seconds=60,
    )
    assert duplicate.allowed is False

    current[0] = base_time + timedelta(seconds=61)
    after_expiry = store.check_and_record(
        "webhook",
        "ops/sample",
        "evt-1",
        ttl_seconds=60,
    )
    assert after_expiry.allowed is True

    different_scope = store.check_and_record(
        "schedule",
        "ops/sample",
        "evt-1",
        ttl_seconds=60,
    )
    assert different_scope.allowed is True

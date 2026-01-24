from datetime import datetime, timedelta, timezone

from skillos.schedules import build_schedule, due_schedules


def test_due_schedules_skip_disabled() -> None:
    now = datetime.now(timezone.utc)
    due = build_schedule("ops/due", now - timedelta(minutes=5))
    disabled = build_schedule(
        "ops/disabled",
        now - timedelta(minutes=5),
        enabled=False,
    )
    future = build_schedule("ops/future", now + timedelta(hours=1))

    records = [due, disabled, future]
    result = due_schedules(records, now=now)

    assert due in result
    assert disabled not in result
    assert future not in result

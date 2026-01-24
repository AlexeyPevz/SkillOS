from datetime import datetime, timedelta, timezone

from skillos.jobs import JobRecord, retry_backoff


def test_job_retry_backoff_progression() -> None:
    assert retry_backoff(1, base_seconds=5) == timedelta(seconds=5)
    assert retry_backoff(2, base_seconds=5) == timedelta(seconds=10)


def test_job_state_transitions_with_retries() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = JobRecord(
        job_id="job-1",
        skill_id="ops/sample",
        payload="ok",
        status="queued",
        retries=0,
        max_retries=1,
        created_at=now,
        updated_at=now,
        next_run_at=now,
        last_error=None,
    )

    record.mark_running(now)
    should_retry = record.mark_failed(now, "boom", base_seconds=5)

    assert should_retry is True
    assert record.status == "queued"
    assert record.retries == 1
    assert record.next_run_at == now + timedelta(seconds=5)

    retry_time = now + timedelta(seconds=5)
    record.mark_running(retry_time)
    should_retry = record.mark_failed(retry_time, "boom", base_seconds=5)

    assert should_retry is False
    assert record.status == "failed"
    assert record.next_run_at is None

import sqlite3
import pytest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from skillos.jobs import JobStore, JobRecord

def test_requeue_dead_letters():
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "jobs.db"
        store = JobStore(db_path)
        
        # Create a job that will fail
        job = store.enqueue("skill_id", max_retries=1)
        
        # Fail it once (retries=1) -> queued
        job.mark_failed(datetime.now(timezone.utc), "error1")
        assert job.status == "queued"
        
        # Fail it twice (retries=2) -> failed
        job.mark_failed(datetime.now(timezone.utc), "error2")
        assert job.status == "failed"
        
        store.save(job)
        
        # Verify it is failed in DB
        reloaded = store.get(job.job_id)
        assert reloaded.status == "failed"
        
        # Requeue
        count = store.requeue_dead_letters(max_retries_bump=2)
        assert count == 1
        
        # Verify
        reloaded = store.get(job.job_id)
        assert reloaded.status == "queued"
        # Original max=1. Bumped by 2 => 3.
        # Original retries=2.
        # Now it has retry capacity (2 < 3).
        assert reloaded.max_retries == 3
        assert reloaded.next_run_at is not None

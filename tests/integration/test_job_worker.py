from pathlib import Path

from skillos.jobs import JobStore, JobWorker, default_jobs_db_path
from skillos.skills.scaffold import scaffold_skill


def test_job_worker_processes_queue(tmp_path: Path) -> None:
    root = tmp_path / "skills_root"
    scaffold_skill("ops/sample", root)

    store = JobStore(default_jobs_db_path(root))
    record = store.enqueue("ops/sample", payload="ok", max_retries=0)

    worker = JobWorker(root, store)
    results = worker.run_once()

    assert results
    updated = store.get(record.job_id)
    assert updated is not None
    assert updated.status == "succeeded"

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.services.job import JobService
from app.worker import JobWorker


def make_job(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "project_id": uuid4(),
        "document_version_id": None,
        "job_type": "execute_search",
        "status": "running",
        "priority": 0,
        "progress_percent": Decimal("25"),
        "current_stage": "working",
        "requested_config": {},
        "result_summary": {},
        "error_code": None,
        "error_message": None,
        "retry_count": 0,
        "max_retries": 3,
        "worker_name": "dead-worker",
        "started_at": datetime.now(UTC) - timedelta(minutes=5),
        "heartbeat_at": datetime.now(UTC) - timedelta(minutes=5),
        "completed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_stale_running_job_is_requeued_with_retry_increment(monkeypatch) -> None:
    worker = JobWorker(worker_name="replacement-worker")
    job = make_job(retry_count=1, max_retries=3)
    db = MagicMock()
    db.scalars.return_value.all.return_value = [job]
    monkeypatch.setattr(worker, "_record_event", MagicMock())

    assert worker.recover_stale_jobs(db) == (1, 0)
    assert job.status == "queued"
    assert job.retry_count == 2
    assert job.worker_name is None
    assert job.heartbeat_at is None
    assert job.started_at is None
    db.commit.assert_called_once()


def test_stale_running_job_fails_when_retries_exhausted(monkeypatch) -> None:
    worker = JobWorker(worker_name="replacement-worker")
    job = make_job(
        job_type="run_extraction",
        requested_config={"extraction_run_id": str(uuid4())},
        retry_count=3,
        max_retries=3,
    )
    db = MagicMock()
    db.scalars.return_value.all.return_value = [job]
    mark_resource_failed = MagicMock()
    monkeypatch.setattr(worker, "_mark_resource_failed", mark_resource_failed)
    monkeypatch.setattr(worker, "_record_event", MagicMock())

    assert worker.recover_stale_jobs(db) == (0, 1)
    assert job.status == "failed"
    assert job.error_code == "worker_heartbeat_timeout"
    mark_resource_failed.assert_called_once_with(db, job)
    db.commit.assert_called_once()


def test_manual_retry_enforces_strict_maximum(monkeypatch) -> None:
    job = make_job(status="failed", retry_count=2, max_retries=2)
    db = MagicMock()
    db.scalar.return_value = job
    service = JobService(db)
    monkeypatch.setattr(service, "_ensure_project", MagicMock())

    with pytest.raises(AppError) as exc_info:
        service.retry(job.project_id, job.id)

    assert exc_info.value.code == "job_retry_limit_exceeded"
    db.commit.assert_not_called()


def test_worker_rolls_back_business_changes_before_failure_commit(monkeypatch) -> None:
    worker = JobWorker(worker_name="test-worker", heartbeat_interval_seconds=999)
    job = make_job(worker_name="test-worker")
    events: list[str] = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, model, job_id):
            return job

        def rollback(self):
            events.append("rollback")
            job.result_summary = {}

        def commit(self):
            events.append("commit")

    db = FakeSession()

    def crash(*args):
        job.result_summary = {"partial": True}
        raise RuntimeError("simulated crash")

    def mark_resource_failed(session, failed_job):
        assert failed_job.result_summary == {}
        events.append("resource_failed")

    monkeypatch.setattr("app.worker.SessionLocal", lambda: db)
    monkeypatch.setattr(worker, "_dispatch", crash)
    monkeypatch.setattr(worker, "_mark_resource_failed", mark_resource_failed)
    monkeypatch.setattr(worker, "_record_event", MagicMock())

    assert worker.process_job(job.id) is False
    assert events == ["rollback", "resource_failed", "commit"]
    assert job.status == "failed"

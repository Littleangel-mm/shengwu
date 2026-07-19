from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.core.errors import AppError
from app.schemas.common import ListResponse
from app.schemas.job import JobEventResponse, JobResponse
from app.services.job import JobService

router = APIRouter()


@router.get("/{project_id}/jobs", response_model=ListResponse[JobResponse])
def list_jobs(
    project_id: UUID,
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> ListResponse[JobResponse]:
    items, total = JobService(db).list(project_id, offset=offset, limit=limit)
    return ListResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{project_id}/jobs/{job_id}", response_model=JobResponse)
def get_job(project_id: UUID, job_id: UUID, db: DbSession) -> JobResponse:
    return JobService(db).get(project_id, job_id)


@router.get("/{project_id}/jobs/{job_id}/events", response_model=list[JobEventResponse])
def list_job_events(project_id: UUID, job_id: UUID, db: DbSession) -> list[JobEventResponse]:
    return JobService(db).events(project_id, job_id)


@router.post("/{project_id}/jobs/{job_id}/retry", response_model=JobResponse)
def retry_job(project_id: UUID, job_id: UUID, db: DbSession) -> JobResponse:
    return JobService(db).retry(project_id, job_id)


@router.post("/{project_id}/jobs/{job_id}/run", response_model=JobResponse)
def run_job_now(project_id: UUID, job_id: UUID, db: DbSession) -> JobResponse:
    job = JobService(db).get(project_id, job_id)
    if job.status not in {"queued", "failed"}:
        raise AppError(code="job_not_runnable", message="任务当前状态不可执行", status_code=409)
    from app.worker import JobWorker

    JobWorker().process_job(job_id)
    db.expire_all()
    return JobService(db).get(project_id, job_id)

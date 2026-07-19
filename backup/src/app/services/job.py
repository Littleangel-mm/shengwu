import builtins
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import ProcessingJob, Project
from app.schemas.job import JobEventResponse, JobResponse


class JobService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _ensure_project(self, project_id: UUID) -> None:
        exists = self.db.scalar(
            select(Project.id).where(Project.id == project_id, Project.deleted_at.is_(None))
        )
        if not exists:
            raise AppError(code="project_not_found", message="项目不存在", status_code=404)

    def list(self, project_id: UUID, *, offset: int, limit: int) -> tuple[list[JobResponse], int]:
        self._ensure_project(project_id)
        where = ProcessingJob.project_id == project_id
        total = self.db.scalar(select(func.count()).select_from(ProcessingJob).where(where)) or 0
        rows = self.db.scalars(
            select(ProcessingJob)
            .where(where)
            .order_by(ProcessingJob.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [JobResponse.model_validate(row) for row in rows], total

    def get(self, project_id: UUID, job_id: UUID) -> JobResponse:
        self._ensure_project(project_id)
        job = self.db.scalar(
            select(ProcessingJob).where(
                ProcessingJob.id == job_id,
                ProcessingJob.project_id == project_id,
            )
        )
        if not job:
            raise AppError(code="job_not_found", message="任务不存在", status_code=404)
        return JobResponse.model_validate(job)

    def events(self, project_id: UUID, job_id: UUID) -> builtins.list[JobEventResponse]:
        self.get(project_id, job_id)
        events = table(self.db, "job_events")
        rows = (
            self.db.execute(select(events).where(events.c.job_id == job_id).order_by(events.c.id))
            .mappings()
            .all()
        )
        return [JobEventResponse.model_validate(row) for row in rows]

    def retry(self, project_id: UUID, job_id: UUID) -> JobResponse:
        self._ensure_project(project_id)
        job = self.db.scalar(
            select(ProcessingJob).where(
                ProcessingJob.id == job_id, ProcessingJob.project_id == project_id
            )
        )
        if not job:
            raise AppError(code="job_not_found", message="任务不存在", status_code=404)
        if job.status not in {"failed", "cancelled"}:
            raise AppError(
                code="job_not_retryable", message="只有失败或取消的任务可以重试", status_code=409
            )
        job.status = "queued"
        job.progress_percent = Decimal("0")
        job.current_stage = "waiting"
        job.error_code = None
        job.error_message = None
        job.retry_count += 1
        job.started_at = None
        job.completed_at = None
        self.db.commit()
        self.db.refresh(job)
        return JobResponse.model_validate(job)

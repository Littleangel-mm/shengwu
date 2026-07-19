import os
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event, Thread
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.db.tables import table
from app.models import DocumentVersion, ProcessingJob
from app.services.parser import DocumentParser
from app.services.storage import LocalStorage

logger = get_logger(__name__)


class JobWorker:
    def __init__(
        self,
        *,
        worker_name: str | None = None,
        heartbeat_interval_seconds: float = 10.0,
        heartbeat_timeout_seconds: float = 60.0,
    ) -> None:
        self.settings = get_settings()
        self.storage = LocalStorage(self.settings)
        self.worker_name = worker_name or f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds

    def _progress(self, db: Session, job: ProcessingJob) -> Callable[[float, str], None]:
        def update_progress(percent: float, stage: str) -> None:
            job.progress_percent = Decimal(str(max(0, min(100, percent))))
            job.current_stage = stage
            job.heartbeat_at = datetime.now(UTC)
            self._record_event(
                db,
                job.id,
                event_type="progress",
                stage=stage,
                progress_percent=job.progress_percent,
                message=f"任务进入阶段：{stage}",
            )
            db.commit()

        return update_progress

    @staticmethod
    def _record_event(
        db: Session,
        job_id: UUID,
        *,
        event_type: str,
        stage: str | None,
        progress_percent: Decimal | None,
        message: str,
        level: str = "info",
        payload: dict | None = None,
    ) -> None:
        events = table(db, "job_events")
        db.execute(
            insert(events).values(
                job_id=job_id,
                event_type=event_type,
                stage=stage,
                progress_percent=progress_percent,
                level=level,
                message=message,
                payload=payload or {},
            )
        )

    def _heartbeat(self, job_id: UUID) -> None:
        with SessionLocal() as db:
            db.execute(
                update(ProcessingJob)
                .where(
                    ProcessingJob.id == job_id,
                    ProcessingJob.status == "running",
                    ProcessingJob.worker_name == self.worker_name,
                )
                .values(heartbeat_at=datetime.now(UTC))
            )
            db.commit()

    def _heartbeat_loop(self, job_id: UUID, stopped: Event) -> None:
        while not stopped.wait(self.heartbeat_interval_seconds):
            try:
                self._heartbeat(job_id)
            except Exception:
                logger.exception("job_heartbeat_failed", extra={"job_id": str(job_id)})

    @staticmethod
    def _resource_reference(job: ProcessingJob) -> tuple[str, str, UUID] | None:
        mappings = {
            "run_extraction": ("extraction_runs", "extraction_run_id"),
            "build_dataset": ("dataset_versions", "dataset_version_id"),
            "train_model": ("ml_runs", "ml_run_id"),
            "run_optimization": ("optimization_runs", "optimization_run_id"),
            "generate_report": ("reports", "report_id"),
        }
        mapping = mappings.get(job.job_type)
        if mapping is None:
            return None
        resource_id = job.requested_config.get(mapping[1])
        if not resource_id:
            return None
        try:
            return mapping[0], "status", UUID(str(resource_id))
        except (TypeError, ValueError):
            return None

    def _mark_resource_failed(self, db: Session, job: ProcessingJob) -> None:
        if job.job_type == "parse_document":
            if job.document_version_id:
                db.execute(
                    update(DocumentVersion)
                    .where(DocumentVersion.id == job.document_version_id)
                    .values(parse_status="failed")
                )
            return
        reference = self._resource_reference(job)
        if reference is None:
            return
        table_name, status_column, resource_id = reference
        resource = table(db, table_name)
        db.execute(
            update(resource)
            .where(resource.c.id == resource_id)
            .values({status_column: "failed"})
        )

    def _fail_job(
        self,
        db: Session,
        job: ProcessingJob,
        *,
        error_code: str,
        error_message: str,
        event_type: str = "failed",
    ) -> None:
        job.status = "failed"
        job.error_code = error_code
        job.error_message = error_message[:4000]
        job.current_stage = "failed"
        job.completed_at = datetime.now(UTC)
        job.heartbeat_at = None
        job.worker_name = None
        self._mark_resource_failed(db, job)
        self._record_event(
            db,
            job.id,
            event_type=event_type,
            stage="failed",
            progress_percent=job.progress_percent,
            level="error",
            message=job.error_message,
            payload={"error_code": error_code},
        )

    def recover_stale_jobs(self, db: Session) -> tuple[int, int]:
        cutoff = datetime.now(UTC) - timedelta(seconds=self.heartbeat_timeout_seconds)
        jobs = db.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.status == "running",
                (
                    (ProcessingJob.heartbeat_at < cutoff)
                    | (
                        ProcessingJob.heartbeat_at.is_(None)
                        & (ProcessingJob.started_at < cutoff)
                    )
                ),
            )
            .with_for_update(skip_locked=True)
        ).all()
        requeued = 0
        failed = 0
        for job in jobs:
            if job.retry_count < job.max_retries:
                job.retry_count += 1
                job.status = "queued"
                job.current_stage = "waiting"
                job.error_code = "worker_heartbeat_timeout"
                job.error_message = "工作进程心跳超时，任务已自动重新排队"
                job.worker_name = None
                job.heartbeat_at = None
                job.started_at = None
                job.completed_at = None
                job.queued_at = datetime.now(UTC)
                job.progress_percent = Decimal("0")
                self._record_event(
                    db,
                    job.id,
                    event_type="requeued",
                    stage="waiting",
                    progress_percent=job.progress_percent,
                    level="warning",
                    message=job.error_message,
                    payload={"retry_count": job.retry_count, "max_retries": job.max_retries},
                )
                requeued += 1
            else:
                self._fail_job(
                    db,
                    job,
                    error_code="worker_heartbeat_timeout",
                    error_message="工作进程心跳超时且已达到最大重试次数",
                    event_type="retries_exhausted",
                )
                failed += 1
        if jobs:
            db.commit()
        else:
            db.rollback()
        return requeued, failed

    def claim_next(self, db: Session) -> UUID | None:
        job = db.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.status == "queued")
            .order_by(ProcessingJob.priority.desc(), ProcessingJob.queued_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            db.rollback()
            return None
        job.status = "running"
        job.current_stage = "starting"
        now = datetime.now(UTC)
        job.started_at = now
        job.heartbeat_at = now
        job.worker_name = self.worker_name
        self._record_event(
            db,
            job.id,
            event_type="started",
            stage="starting",
            progress_percent=job.progress_percent,
            message="后台工作进程已领取任务",
        )
        db.commit()
        return job.id

    def process_job(self, job_id: UUID) -> bool:
        with SessionLocal() as db:
            job = db.get(ProcessingJob, job_id)
            if not job:
                return False
            if job.status == "queued":
                job.status = "running"
                now = datetime.now(UTC)
                job.started_at = now
                job.heartbeat_at = now
                job.worker_name = self.worker_name
                db.commit()
            progress = self._progress(db, job)
            heartbeat_stopped = Event()
            heartbeat_thread = Thread(
                target=self._heartbeat_loop,
                args=(job_id, heartbeat_stopped),
                name=f"job-heartbeat-{job_id}",
                daemon=True,
            )
            heartbeat_thread.start()
            try:
                result = self._dispatch(db, job, progress)
                job.status = "completed"
                job.progress_percent = Decimal("100")
                job.current_stage = "completed"
                job.result_summary = result or {}
                job.completed_at = datetime.now(UTC)
                job.error_code = None
                job.error_message = None
                job.heartbeat_at = None
                job.worker_name = None
                self._record_event(
                    db,
                    job.id,
                    event_type="completed",
                    stage="completed",
                    progress_percent=Decimal("100"),
                    message="任务处理完成",
                    payload=result or {},
                )
                db.commit()
                return True
            except AppError as exc:
                db.rollback()
                job = db.get(ProcessingJob, job_id)
                if job:
                    self._fail_job(
                        db,
                        job,
                        error_code=exc.code,
                        error_message=exc.message,
                    )
                    db.commit()
                logger.warning("job_failed", extra={"job_id": str(job_id), "error_code": exc.code})
                return False
            except Exception as exc:
                db.rollback()
                job = db.get(ProcessingJob, job_id)
                if job:
                    self._fail_job(
                        db,
                        job,
                        error_code="worker_error",
                        error_message=str(exc),
                    )
                    db.commit()
                logger.exception("job_crashed", extra={"job_id": str(job_id)})
                return False
            finally:
                heartbeat_stopped.set()
                heartbeat_thread.join(timeout=self.heartbeat_interval_seconds + 1)

    def _dispatch(
        self,
        db: Session,
        job: ProcessingJob,
        progress: Callable[[float, str], None],
    ) -> dict:
        if job.job_type == "parse_document":
            if not job.document_version_id:
                raise AppError(
                    code="missing_document_version", message="解析任务缺少文献版本", status_code=422
                )
            return DocumentParser(db, self.storage).parse(job.document_version_id, progress)
        if job.job_type == "execute_search":
            from app.services.search import SearchService

            return SearchService(db).execute(UUID(job.requested_config["search_run_id"]), progress)
        if job.job_type == "translate_document":
            from app.services.translation import TranslationService

            return TranslationService(db).execute(
                UUID(job.requested_config["document_version_id"]),
                job.requested_config.get("target_language", "zh-CN"),
                bool(job.requested_config.get("overwrite", False)),
                progress,
            )
        if job.job_type == "discover_terms":
            from app.services.term import TermService

            return TermService(db).discover(
                UUID(job.requested_config["search_run_id"]),
                progress,
                min_occurrences=int(job.requested_config.get("min_occurrences", 2)),
                max_candidates=int(job.requested_config.get("max_candidates", 500)),
            )
        if job.job_type == "run_extraction":
            from app.services.extraction import ExtractionService

            return ExtractionService(db).execute(
                UUID(job.requested_config["extraction_run_id"]), progress
            )
        if job.job_type == "build_dataset":
            from app.services.dataset import DatasetService

            return DatasetService(db, self.storage).build(
                UUID(job.requested_config["dataset_version_id"]), progress
            )
        if job.job_type == "train_model":
            from app.services.ml import MLService

            return MLService(db, self.storage).train(
                UUID(job.requested_config["ml_run_id"]), progress
            )
        if job.job_type == "run_optimization":
            from app.services.ml import MLService

            return MLService(db, self.storage).optimize(
                UUID(job.requested_config["optimization_run_id"]), progress
            )
        if job.job_type == "generate_report":
            from app.services.report import ReportService

            return ReportService(db, self.storage).generate(
                UUID(job.requested_config["report_id"]), progress
            )
        raise AppError(
            code="unsupported_job_type",
            message=f"不支持的任务类型：{job.job_type}",
            status_code=422,
        )

    def run_forever(self) -> None:
        configure_logging(self.settings.log_level)
        logger.info("worker_started")
        while True:
            with SessionLocal() as db:
                requeued, failed = self.recover_stale_jobs(db)
                if requeued or failed:
                    logger.warning(
                        "stale_jobs_recovered",
                        extra={"requeued": requeued, "failed": failed},
                    )
                job_id = self.claim_next(db)
            if job_id:
                self.process_job(job_id)
                continue
            time.sleep(self.settings.worker_poll_seconds)


def run() -> None:
    JobWorker().run_forever()


if __name__ == "__main__":
    run()

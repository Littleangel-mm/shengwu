import time
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.db.tables import table
from app.models import ProcessingJob
from app.services.parser import DocumentParser
from app.services.storage import LocalStorage

logger = get_logger(__name__)


class JobWorker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.storage = LocalStorage(self.settings)

    def _progress(self, db: Session, job: ProcessingJob) -> Callable[[float, str], None]:
        def update_progress(percent: float, stage: str) -> None:
            job.progress_percent = Decimal(str(max(0, min(100, percent))))
            job.current_stage = stage
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
        from datetime import UTC, datetime

        job.started_at = datetime.now(UTC)
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
                db.commit()
            progress = self._progress(db, job)
            try:
                result = self._dispatch(db, job, progress)
                from datetime import UTC, datetime

                job.status = "completed"
                job.progress_percent = Decimal("100")
                job.current_stage = "completed"
                job.result_summary = result or {}
                job.completed_at = datetime.now(UTC)
                job.error_code = None
                job.error_message = None
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
                    job.status = "failed"
                    job.error_code = exc.code
                    job.error_message = exc.message
                    job.current_stage = "failed"
                    self._record_event(
                        db,
                        job.id,
                        event_type="failed",
                        stage="failed",
                        progress_percent=job.progress_percent,
                        level="error",
                        message=exc.message,
                        payload={"error_code": exc.code},
                    )
                    db.commit()
                logger.warning("job_failed", extra={"job_id": str(job_id), "error_code": exc.code})
                return False
            except Exception as exc:
                db.rollback()
                job = db.get(ProcessingJob, job_id)
                if job:
                    job.status = "failed"
                    job.error_code = "worker_error"
                    job.error_message = str(exc)[:4000]
                    job.current_stage = "failed"
                    self._record_event(
                        db,
                        job.id,
                        event_type="failed",
                        stage="failed",
                        progress_percent=job.progress_percent,
                        level="error",
                        message=job.error_message,
                        payload={"error_code": "worker_error"},
                    )
                    db.commit()
                logger.exception("job_crashed", extra={"job_id": str(job_id)})
                return False

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
                job_id = self.claim_next(db)
            if job_id:
                self.process_job(job_id)
                continue
            time.sleep(self.settings.worker_poll_seconds)


def run() -> None:
    JobWorker().run_forever()


if __name__ == "__main__":
    run()

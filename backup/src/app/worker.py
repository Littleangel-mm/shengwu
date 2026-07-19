import time
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
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
            db.commit()

        return update_progress

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

            return TermService(db).discover(UUID(job.requested_config["search_run_id"]), progress)
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

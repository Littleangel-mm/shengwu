from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.deps import ActorId, DbSession
from app.core.config import get_settings
from app.schemas.report import ReportCreate
from app.schemas.workflow import TaskAccepted
from app.services.report import ReportService
from app.services.storage import LocalStorage

router = APIRouter()


def service(db: DbSession) -> ReportService:
    return ReportService(db, LocalStorage(get_settings()))


@router.post("/{project_id}/reports", response_model=TaskAccepted, status_code=202)
def create_report(project_id: UUID, payload: ReportCreate, db: DbSession, actor_id: ActorId):
    return service(db).create(project_id, payload, actor_id)


@router.get("/{project_id}/reports", response_model=list[dict[str, Any]])
def list_reports(project_id: UUID, db: DbSession):
    return service(db).list(project_id)


@router.get("/{project_id}/reports/{report_id}", response_model=dict[str, Any])
def get_report(project_id: UUID, report_id: UUID, db: DbSession):
    return service(db).get(project_id, report_id)


@router.get("/{project_id}/reports/{report_id}/download")
def download_report(project_id: UUID, report_id: UUID, db: DbSession):
    path, filename = service(db).output_path(project_id, report_id)
    return FileResponse(
        path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

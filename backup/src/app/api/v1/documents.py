from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import ActorId, DbSession
from app.core.config import get_settings
from app.schemas.common import ListResponse
from app.schemas.document import DocumentResponse, UploadBatchResponse
from app.schemas.job import JobResponse
from app.schemas.workflow import TaskAccepted, TranslationCreate
from app.services.document import DocumentService
from app.services.storage import LocalStorage
from app.services.translation import TranslationService

router = APIRouter()


@router.post("/{project_id}/documents/upload", response_model=UploadBatchResponse)
def upload_documents(
    project_id: UUID,
    db: DbSession,
    actor_id: ActorId,
    files: list[UploadFile] = File(...),
) -> UploadBatchResponse:
    service = DocumentService(db, LocalStorage(get_settings()))
    return service.upload_many(project_id=project_id, files=files, actor_id=actor_id)


@router.get("/{project_id}/documents", response_model=ListResponse[DocumentResponse])
def list_documents(
    project_id: UUID,
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> ListResponse[DocumentResponse]:
    items, total = DocumentService(db, LocalStorage(get_settings())).list(
        project_id=project_id,
        offset=offset,
        limit=limit,
    )
    return ListResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{project_id}/documents/{document_id}")
def get_document(project_id: UUID, document_id: UUID, db: DbSession):
    return DocumentService(db, LocalStorage(get_settings())).detail(project_id, document_id)


@router.get("/{project_id}/documents/{document_id}/source")
def download_source(project_id: UUID, document_id: UUID, db: DbSession):
    path, filename, media_type = DocumentService(db, LocalStorage(get_settings())).source_path(
        project_id, document_id
    )
    return FileResponse(path, filename=filename, media_type=media_type)


@router.post(
    "/{project_id}/documents/{document_id}/parse", response_model=JobResponse, status_code=202
)
def reparse_document(project_id: UUID, document_id: UUID, db: DbSession, actor_id: ActorId):
    return DocumentService(db, LocalStorage(get_settings())).enqueue_reparse(
        project_id, document_id, actor_id
    )


@router.post(
    "/{project_id}/document-versions/{version_id}/translate",
    response_model=TaskAccepted,
    status_code=202,
)
def translate_document(
    project_id: UUID, version_id: UUID, payload: TranslationCreate, db: DbSession, actor_id: ActorId
):
    return TranslationService(db).enqueue(project_id, version_id, payload, actor_id)

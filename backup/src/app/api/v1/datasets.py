from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response, status
from fastapi.responses import FileResponse

from app.api.deps import ActorId, DbSession
from app.core.config import get_settings
from app.schemas.dataset import (
    DatasetBuildCreate,
    DatasetCellUpdate,
    DatasetFieldCreate,
    DatasetRowCreate,
    DatasetVersionClone,
)
from app.schemas.workflow import TaskAccepted
from app.services.dataset import DatasetService
from app.services.storage import LocalStorage

router = APIRouter()


def service(db: DbSession) -> DatasetService:
    return DatasetService(db, LocalStorage(get_settings()))


@router.post("/{project_id}/datasets/from-extraction", response_model=TaskAccepted, status_code=202)
def create_dataset(project_id: UUID, payload: DatasetBuildCreate, db: DbSession, actor_id: ActorId):
    return service(db).create_from_extraction(project_id, payload, actor_id)


@router.get("/{project_id}/datasets", response_model=list[dict[str, Any]])
def list_datasets(project_id: UUID, db: DbSession):
    return service(db).list_datasets(project_id)


@router.get("/{project_id}/datasets/{dataset_id}/versions", response_model=list[dict[str, Any]])
def list_dataset_versions(project_id: UUID, dataset_id: UUID, db: DbSession):
    return service(db).list_versions(project_id, dataset_id)


@router.get("/{project_id}/dataset-versions/{version_id}", response_model=dict[str, Any])
def get_dataset_version(
    project_id: UUID, version_id: UUID, db: DbSession, offset: int = 0, limit: int = 200
):
    return service(db).get_version(project_id, version_id, offset, min(limit, 1000))


@router.post(
    "/{project_id}/dataset-versions/{version_id}/fields",
    response_model=dict[str, Any],
    status_code=201,
)
def add_dataset_field(
    project_id: UUID,
    version_id: UUID,
    payload: DatasetFieldCreate,
    db: DbSession,
    actor_id: ActorId,
):
    return service(db).add_field(project_id, version_id, payload, actor_id)


@router.post(
    "/{project_id}/dataset-versions/{version_id}/rows",
    response_model=dict[str, Any],
    status_code=201,
)
def add_dataset_row(
    project_id: UUID, version_id: UUID, payload: DatasetRowCreate, db: DbSession, actor_id: ActorId
):
    return service(db).add_row(project_id, version_id, payload, actor_id)


@router.patch(
    "/{project_id}/dataset-versions/{version_id}/rows/{row_id}/cells/{field_id}",
    response_model=dict[str, Any],
)
def update_dataset_cell(
    project_id: UUID,
    version_id: UUID,
    row_id: UUID,
    field_id: UUID,
    payload: DatasetCellUpdate,
    db: DbSession,
    actor_id: ActorId,
):
    return service(db).update_cell(project_id, version_id, row_id, field_id, payload, actor_id)


@router.delete(
    "/{project_id}/dataset-versions/{version_id}/rows/{row_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_dataset_row(
    project_id: UUID, version_id: UUID, row_id: UUID, db: DbSession, actor_id: ActorId
):
    service(db).delete_row(project_id, version_id, row_id, actor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{project_id}/dataset-versions/{version_id}/freeze", response_model=dict[str, Any])
def freeze_dataset(project_id: UUID, version_id: UUID, db: DbSession, actor_id: ActorId):
    return service(db).freeze(project_id, version_id, actor_id)


@router.post(
    "/{project_id}/dataset-versions/{version_id}/clone",
    response_model=dict[str, Any],
    status_code=201,
)
def clone_dataset_version(
    project_id: UUID,
    version_id: UUID,
    payload: DatasetVersionClone,
    db: DbSession,
    actor_id: ActorId,
):
    return service(db).clone_version(project_id, version_id, payload, actor_id)


@router.get("/{project_id}/dataset-versions/{version_id}/export.xlsx")
def export_dataset(project_id: UUID, version_id: UUID, db: DbSession):
    path = service(db).export_xlsx(project_id, version_id)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )

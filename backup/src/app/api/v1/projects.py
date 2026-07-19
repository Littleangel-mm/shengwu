from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentActorId, DbSession, ProjectEditor, ProjectMember
from app.schemas.common import ListResponse
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
from app.services.project import ProjectService

router = APIRouter()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate, db: DbSession, actor_id: CurrentActorId
) -> ProjectResponse:
    return ProjectService(db).create(payload, actor_id)


@router.get("", response_model=ListResponse[ProjectResponse])
def list_projects(
    db: DbSession,
    actor_id: CurrentActorId,
    organization_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> ListResponse[ProjectResponse]:
    items, total = ProjectService(db).list(
        organization_id=organization_id,
        offset=offset,
        limit=limit,
        actor_id=actor_id,
    )
    return ListResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: UUID, db: DbSession, _member: ProjectMember) -> ProjectResponse:
    return ProjectService(db).get(project_id)


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    db: DbSession,
    _editor: ProjectEditor,
) -> ProjectResponse:
    return ProjectService(db).update(project_id, payload)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: UUID, db: DbSession, _editor: ProjectEditor) -> Response:
    ProjectService(db).soft_delete(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

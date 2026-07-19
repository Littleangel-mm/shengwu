from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentActorId, DbSession, ProjectAdmin, ProjectEditor, ProjectMember
from app.schemas.common import ListResponse
from app.schemas.project import (
    ProjectCreate,
    ProjectMemberInvite,
    ProjectMemberResponse,
    ProjectMembershipResponse,
    ProjectMemberUpdate,
    ProjectResponse,
    ProjectUpdate,
)
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


@router.get("/{project_id}/membership", response_model=ProjectMembershipResponse)
def get_current_project_membership(
    project_id: UUID,
    db: DbSession,
    actor_id: ProjectMember,
) -> ProjectMembershipResponse:
    return ProjectService(db).current_membership(project_id, actor_id)


@router.get(
    "/{project_id}/members",
    response_model=list[ProjectMemberResponse],
)
def list_project_members(
    project_id: UUID,
    db: DbSession,
    _member: ProjectMember,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ProjectMemberResponse]:
    items, _total = ProjectService(db).list_members(project_id, offset, limit)
    return items


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def invite_project_member(
    project_id: UUID,
    payload: ProjectMemberInvite,
    db: DbSession,
    admin: ProjectAdmin,
) -> ProjectMemberResponse:
    return ProjectService(db).invite_member(project_id, payload, admin)


@router.patch(
    "/{project_id}/members/{user_id}",
    response_model=ProjectMemberResponse,
)
def update_project_member(
    project_id: UUID,
    user_id: UUID,
    payload: ProjectMemberUpdate,
    db: DbSession,
    admin: ProjectAdmin,
) -> ProjectMemberResponse:
    return ProjectService(db).update_member(project_id, user_id, payload, admin)


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_project_member(
    project_id: UUID,
    user_id: UUID,
    db: DbSession,
    admin: ProjectAdmin,
) -> Response:
    ProjectService(db).remove_member(project_id, user_id, admin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

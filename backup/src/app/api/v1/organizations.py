from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentActorId, DbSession, OrganizationAdmin, OrganizationMember
from app.schemas.common import ListResponse
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationMemberInvite,
    OrganizationMemberResponse,
    OrganizationMemberUpdate,
    OrganizationResponse,
)
from app.services.organization import OrganizationService

router = APIRouter()


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    db: DbSession,
    actor_id: CurrentActorId,
) -> OrganizationResponse:
    return OrganizationService(db).create(payload, actor_id)


@router.get("", response_model=ListResponse[OrganizationResponse])
def list_organizations(
    db: DbSession,
    actor_id: CurrentActorId,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> ListResponse[OrganizationResponse]:
    items, total = OrganizationService(db).list(actor_id=actor_id, offset=offset, limit=limit)
    return ListResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{organization_id}", response_model=OrganizationResponse)
def get_organization(
    organization_id: UUID, db: DbSession, actor_id: CurrentActorId
) -> OrganizationResponse:
    return OrganizationService(db).get(organization_id, actor_id)


@router.get(
    "/{organization_id}/members",
    response_model=list[OrganizationMemberResponse],
)
def list_organization_members(
    organization_id: UUID,
    db: DbSession,
    _member: OrganizationMember,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[OrganizationMemberResponse]:
    items, _total = OrganizationService(db).list_members(organization_id, offset, limit)
    return items


@router.post(
    "/{organization_id}/members",
    response_model=OrganizationMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def invite_organization_member(
    organization_id: UUID,
    payload: OrganizationMemberInvite,
    db: DbSession,
    admin: OrganizationAdmin,
) -> OrganizationMemberResponse:
    return OrganizationService(db).invite_member(organization_id, payload, admin)


@router.patch(
    "/{organization_id}/members/{user_id}",
    response_model=OrganizationMemberResponse,
)
def update_organization_member(
    organization_id: UUID,
    user_id: UUID,
    payload: OrganizationMemberUpdate,
    db: DbSession,
    admin: OrganizationAdmin,
) -> OrganizationMemberResponse:
    return OrganizationService(db).update_member(organization_id, user_id, payload, admin)


@router.delete(
    "/{organization_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_organization_member(
    organization_id: UUID,
    user_id: UUID,
    db: DbSession,
    admin: OrganizationAdmin,
) -> Response:
    OrganizationService(db).remove_member(organization_id, user_id, admin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

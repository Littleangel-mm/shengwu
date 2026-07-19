from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentActorId, DbSession
from app.schemas.common import ListResponse
from app.schemas.organization import OrganizationCreate, OrganizationResponse
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

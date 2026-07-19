from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import ActorId, DbSession
from app.schemas.common import ListResponse
from app.schemas.system import (
    ConversionRuleCreate,
    ConvertValueRequest,
    ExternalServiceCreate,
    UnitCreate,
)
from app.services.system import SystemService

router = APIRouter()


@router.get("/units", response_model=list[dict[str, Any]])
def list_units(db: DbSession):
    return SystemService(db).list_units()


@router.post("/units", response_model=dict[str, Any], status_code=201)
def create_unit(payload: UnitCreate, db: DbSession):
    return SystemService(db).create_unit(payload)


@router.post("/conversion-rules", response_model=dict[str, Any], status_code=201)
def create_conversion_rule(
    payload: ConversionRuleCreate,
    db: DbSession,
    actor_id: ActorId,
    organization_id: UUID | None = None,
):
    return SystemService(db).create_conversion_rule(organization_id, payload, actor_id)


@router.post("/convert", response_model=dict[str, Any])
def convert_value(payload: ConvertValueRequest, db: DbSession):
    return SystemService(db).convert(payload)


@router.get("/projects/{project_id}/audit-logs", response_model=ListResponse[dict[str, Any]])
def list_audit(
    project_id: UUID,
    db: DbSession,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    items, total = SystemService(db).list_audit(project_id, offset, limit)
    return ListResponse(items=items, total=total, offset=offset, limit=limit)


@router.post(
    "/organizations/{organization_id}/external-services",
    response_model=dict[str, Any],
    status_code=201,
)
def create_external_service(
    organization_id: UUID,
    payload: ExternalServiceCreate,
    db: DbSession,
    actor_id: ActorId,
    project_id: UUID | None = None,
):
    return SystemService(db).create_external_service(organization_id, project_id, payload, actor_id)


@router.get(
    "/organizations/{organization_id}/external-services", response_model=list[dict[str, Any]]
)
def list_external_services(organization_id: UUID, db: DbSession, project_id: UUID | None = None):
    return SystemService(db).list_external_services(organization_id, project_id)

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import ActorId, DbSession
from app.schemas.common import ListResponse
from app.schemas.workflow import ExtractionCreate, TaskAccepted
from app.services.extraction import ExtractionService

router = APIRouter()


@router.post("/{project_id}/extraction-runs", response_model=TaskAccepted, status_code=202)
def create_extraction(
    project_id: UUID, payload: ExtractionCreate, db: DbSession, actor_id: ActorId
):
    return ExtractionService(db).create(project_id, payload, actor_id)


@router.get("/{project_id}/extraction-runs", response_model=list[dict[str, Any]])
def list_extractions(project_id: UUID, db: DbSession):
    return ExtractionService(db).list_runs(project_id)


@router.get(
    "/{project_id}/extraction-runs/{run_id}/records", response_model=ListResponse[dict[str, Any]]
)
def list_extraction_records(
    project_id: UUID,
    run_id: UUID,
    db: DbSession,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    items, total = ExtractionService(db).list_records(project_id, run_id, offset, limit)
    return ListResponse(items=items, total=total, offset=offset, limit=limit)

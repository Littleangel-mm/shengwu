from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import ActorId, DbSession
from app.schemas.common import ListResponse
from app.schemas.workflow import SearchCreate, SearchResultReview, TaskAccepted
from app.services.search import SearchService

router = APIRouter()


@router.post("/{project_id}/search-runs", response_model=TaskAccepted, status_code=202)
def create_search(
    project_id: UUID, payload: SearchCreate, db: DbSession, actor_id: ActorId
) -> TaskAccepted:
    return SearchService(db).create(project_id, payload, actor_id)


@router.get("/{project_id}/search-runs", response_model=ListResponse[dict[str, Any]])
def list_searches(
    project_id: UUID,
    db: DbSession,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    items, total = SearchService(db).list_runs(project_id, offset, limit)
    return ListResponse(items=items, total=total, offset=offset, limit=limit)


@router.get(
    "/{project_id}/search-runs/{run_id}/results", response_model=ListResponse[dict[str, Any]]
)
def list_search_results(
    project_id: UUID,
    run_id: UUID,
    db: DbSession,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    items, total = SearchService(db).list_results(project_id, run_id, offset, limit)
    return ListResponse(items=items, total=total, offset=offset, limit=limit)


@router.patch(
    "/{project_id}/search-runs/{run_id}/results/{result_id}", response_model=dict[str, Any]
)
def review_search_result(
    project_id: UUID,
    run_id: UUID,
    result_id: UUID,
    payload: SearchResultReview,
    db: DbSession,
    actor_id: ActorId,
):
    return SearchService(db).review_result(
        project_id, run_id, result_id, payload.model_dump(), actor_id
    )

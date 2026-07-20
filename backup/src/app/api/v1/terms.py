from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import ActorId, DbSession
from app.schemas.common import ListResponse
from app.schemas.workflow import (
    FieldDiscoveryCreate,
    FieldSchemaCreate,
    FieldSchemaFromCandidates,
    FieldSchemaUpdate,
    TaskAccepted,
    TermCategoryCreate,
    TermCategoryUpdate,
    TermCreate,
    TermDiscoveryCreate,
    TermMerge,
    TermSplit,
    TermUpdate,
)
from app.services.term import TermService

router = APIRouter()


@router.post("/{project_id}/term-categories", response_model=dict[str, Any], status_code=201)
def create_category(project_id: UUID, payload: TermCategoryCreate, db: DbSession):
    return TermService(db).create_category(project_id, payload)


@router.get("/{project_id}/term-categories", response_model=list[dict[str, Any]])
def list_categories(project_id: UUID, db: DbSession):
    return TermService(db).list_categories(project_id)


@router.post(
    "/{project_id}/term-categories/apply-default-template",
    response_model=list[dict[str, Any]],
)
def apply_default_category_template(project_id: UUID, db: DbSession):
    return TermService(db).apply_default_category_template(project_id)


@router.patch("/{project_id}/term-categories/{category_id}", response_model=dict[str, Any])
def update_category(
    project_id: UUID, category_id: UUID, payload: TermCategoryUpdate, db: DbSession
):
    return TermService(db).update_category(project_id, category_id, payload)


@router.delete("/{project_id}/term-categories/{category_id}", response_model=dict[str, Any])
def delete_category(project_id: UUID, category_id: UUID, db: DbSession):
    return TermService(db).delete_category(project_id, category_id)


@router.post("/{project_id}/terms", response_model=dict[str, Any], status_code=201)
def create_term(project_id: UUID, payload: TermCreate, db: DbSession, actor_id: ActorId):
    return TermService(db).create_term(project_id, payload, actor_id)


@router.get("/{project_id}/terms", response_model=ListResponse[dict[str, Any]])
def list_terms(
    project_id: UUID,
    db: DbSession,
    category_id: UUID | None = None,
    status: str | None = Query(default=None, max_length=32),
    is_selected: bool | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    items, total = TermService(db).list_terms(
        project_id, category_id, status, is_selected, offset, limit
    )
    return ListResponse(items=items, total=total, offset=offset, limit=limit)


# 注意：必须先于 /terms/{term_id} 注册，否则 "synonym-suggestions" 会被当作 term_id 解析。
@router.get("/{project_id}/terms/synonym-suggestions", response_model=list[dict[str, Any]])
def suggest_term_synonyms(project_id: UUID, db: DbSession):
    return TermService(db).suggest_synonyms(project_id)


@router.get("/{project_id}/terms/{term_id}", response_model=dict[str, Any])
def get_term(project_id: UUID, term_id: UUID, db: DbSession):
    return TermService(db).get_term(project_id, term_id)


@router.patch("/{project_id}/terms/{term_id}", response_model=dict[str, Any])
def update_term(
    project_id: UUID, term_id: UUID, payload: TermUpdate, db: DbSession, actor_id: ActorId
):
    return TermService(db).update_term(project_id, term_id, payload, actor_id)


@router.delete("/{project_id}/terms/{term_id}", response_model=dict[str, Any])
def delete_term(project_id: UUID, term_id: UUID, db: DbSession, actor_id: ActorId):
    return TermService(db).delete_term(project_id, term_id, actor_id)


@router.post("/{project_id}/terms/merge", response_model=dict[str, Any])
def merge_terms(project_id: UUID, payload: TermMerge, db: DbSession, actor_id: ActorId):
    return TermService(db).merge_terms(project_id, payload, actor_id)


@router.post("/{project_id}/terms/{term_id}/split", response_model=list[dict[str, Any]])
def split_term(
    project_id: UUID,
    term_id: UUID,
    payload: TermSplit,
    db: DbSession,
    actor_id: ActorId,
):
    return TermService(db).split_term(project_id, term_id, payload, actor_id)


@router.post("/{project_id}/term-discovery", response_model=TaskAccepted, status_code=202)
def discover_terms(
    project_id: UUID, payload: TermDiscoveryCreate, db: DbSession, actor_id: ActorId
):
    return TermService(db).enqueue_discovery(project_id, payload, actor_id)


@router.post("/{project_id}/field-discovery", response_model=TaskAccepted, status_code=202)
def discover_fields(
    project_id: UUID, payload: FieldDiscoveryCreate, db: DbSession, actor_id: ActorId
):
    return TermService(db).enqueue_field_discovery(project_id, payload, actor_id)


@router.get("/{project_id}/field-candidates", response_model=list[dict[str, Any]])
def list_field_candidates(project_id: UUID, db: DbSession):
    return TermService(db).list_field_candidates(project_id)


@router.post("/{project_id}/field-schemas", response_model=dict[str, Any], status_code=201)
def create_field_schema(
    project_id: UUID, payload: FieldSchemaCreate, db: DbSession, actor_id: ActorId
):
    return TermService(db).create_field_schema(project_id, payload, actor_id)


@router.post(
    "/{project_id}/field-schemas/from-candidates",
    response_model=dict[str, Any],
    status_code=201,
)
def create_field_schema_from_candidates(
    project_id: UUID, payload: FieldSchemaFromCandidates, db: DbSession, actor_id: ActorId
):
    return TermService(db).create_field_schema_from_candidates(project_id, payload, actor_id)


@router.get("/{project_id}/field-schemas", response_model=list[dict[str, Any]])
def list_field_schemas(project_id: UUID, db: DbSession):
    return TermService(db).list_field_schemas(project_id)


@router.get("/{project_id}/field-schemas/{schema_id}", response_model=dict[str, Any])
def get_field_schema(project_id: UUID, schema_id: UUID, db: DbSession):
    return TermService(db).get_field_schema(project_id, schema_id)


@router.patch("/{project_id}/field-schemas/{schema_id}", response_model=dict[str, Any])
def update_field_schema(
    project_id: UUID,
    schema_id: UUID,
    payload: FieldSchemaUpdate,
    db: DbSession,
):
    return TermService(db).update_field_schema(project_id, schema_id, payload)


@router.post("/{project_id}/field-schemas/{schema_id}/freeze", response_model=dict[str, Any])
def freeze_field_schema(project_id: UUID, schema_id: UUID, db: DbSession, actor_id: ActorId):
    return TermService(db).freeze_field_schema(project_id, schema_id, actor_id)

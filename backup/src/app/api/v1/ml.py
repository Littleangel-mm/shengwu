from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.api.deps import ActorId, DbSession
from app.core.config import get_settings
from app.schemas.ml import (
    MLRunCreate,
    MultiPredictionRequest,
    OptimizationCreate,
    PredictionRequest,
)
from app.schemas.workflow import TaskAccepted
from app.services.ml import MLService
from app.services.storage import LocalStorage

router = APIRouter()


def service(db: DbSession) -> MLService:
    return MLService(db, LocalStorage(get_settings()))


@router.post("/{project_id}/ml-runs", response_model=TaskAccepted, status_code=202)
def create_ml_run(project_id: UUID, payload: MLRunCreate, db: DbSession, actor_id: ActorId):
    return service(db).create_run(project_id, payload, actor_id)


@router.get(
    "/{project_id}/dataset-versions/{dataset_version_id}/derived-feature-candidates",
    response_model=list[dict[str, Any]],
)
def suggest_derived_features(project_id: UUID, dataset_version_id: UUID, db: DbSession):
    return service(db).suggest_derived_features(project_id, dataset_version_id)


@router.get("/{project_id}/ml-runs", response_model=list[dict[str, Any]])
def list_ml_runs(project_id: UUID, db: DbSession):
    return service(db).list_runs(project_id)


@router.get("/{project_id}/ml-runs/{run_id}", response_model=dict[str, Any])
def get_ml_run(project_id: UUID, run_id: UUID, db: DbSession):
    return service(db).get_run(project_id, run_id)


@router.post(
    "/{project_id}/ml-runs/{run_id}/models/{model_id}/select", response_model=dict[str, Any]
)
def select_model(project_id: UUID, run_id: UUID, model_id: UUID, db: DbSession):
    return service(db).select_model(project_id, run_id, model_id)


@router.post("/{project_id}/ml-models/{model_id}/predict", response_model=dict[str, Any])
def predict(project_id: UUID, model_id: UUID, payload: PredictionRequest, db: DbSession):
    return service(db).predict(project_id, model_id, payload)


@router.post("/{project_id}/ml-models/predict-many", response_model=dict[str, Any])
def predict_many(project_id: UUID, payload: MultiPredictionRequest, db: DbSession):
    return service(db).predict_many(project_id, payload)


@router.post("/{project_id}/optimization-runs", response_model=TaskAccepted, status_code=202)
def create_optimization(
    project_id: UUID, payload: OptimizationCreate, db: DbSession, actor_id: ActorId
):
    return service(db).create_optimization(project_id, payload, actor_id)


@router.get("/{project_id}/optimization-runs", response_model=list[dict[str, Any]])
def list_optimizations(project_id: UUID, db: DbSession):
    return service(db).list_optimizations(project_id)


@router.get("/{project_id}/optimization-runs/{run_id}", response_model=dict[str, Any])
def get_optimization(project_id: UUID, run_id: UUID, db: DbSession):
    return service(db).get_optimization(project_id, run_id)

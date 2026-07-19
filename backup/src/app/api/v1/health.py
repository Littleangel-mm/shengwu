from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.api.deps import DbSession
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.health import HealthResponse
from app.services.ocr import PaddleOCRService

router = APIRouter(prefix="/health")


@router.get("/live", response_model=HealthResponse)
def liveness() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__, timestamp=datetime.now(UTC))


@router.get("/ready", response_model=HealthResponse)
def readiness(db: DbSession) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise AppError(
            code="database_unavailable",
            message="数据库当前不可用",
            status_code=503,
        ) from exc
    return HealthResponse(status="ready", version=__version__, timestamp=datetime.now(UTC))


@router.get("/ocr", response_model=dict)
def ocr_readiness() -> dict:
    return PaddleOCRService(get_settings()).status()

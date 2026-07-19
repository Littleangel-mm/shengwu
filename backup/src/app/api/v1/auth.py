from fastapi import APIRouter, Request

from app.api.deps import CurrentActorId, DbSession
from app.schemas.auth import TokenResponse, UserLogin, UserRegister, UserResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth")


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: UserRegister, db: DbSession) -> TokenResponse:
    return AuthService(db).register(payload)


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, request: Request, db: DbSession) -> TokenResponse:
    client_host = request.client.host if request.client else "unknown"
    return AuthService(db).login(payload, client_host)


@router.get("/me", response_model=UserResponse)
def me(db: DbSession, actor_id: CurrentActorId) -> UserResponse:
    return AuthService(db).me(actor_id)

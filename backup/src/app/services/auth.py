from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import AppUser
from app.schemas.auth import TokenResponse, UserLogin, UserRegister, UserResponse


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def register(self, payload: UserRegister) -> TokenResponse:
        user = AppUser(
            email=payload.email.casefold(),
            display_name=payload.display_name.strip(),
            password_hash=hash_password(payload.password),
            auth_provider="local",
            preferences={},
        )
        self.db.add(user)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AppError(code="email_exists", message="邮箱已注册", status_code=409) from exc
        self.db.refresh(user)
        token, expires = create_access_token(user.id)
        return TokenResponse(
            access_token=token,
            expires_at=expires,
            user=UserResponse.model_validate(user),
        )

    def login(self, payload: UserLogin) -> TokenResponse:
        user = self.db.scalar(
            select(AppUser).where(
                func.lower(AppUser.email) == payload.email.casefold(),
                AppUser.deleted_at.is_(None),
            )
        )
        if not user or not verify_password(payload.password, user.password_hash):
            raise AppError(code="invalid_credentials", message="邮箱或密码错误", status_code=401)
        if user.status != "active":
            raise AppError(code="user_disabled", message="用户已停用", status_code=403)
        token, expires = create_access_token(user.id)
        return TokenResponse(
            access_token=token,
            expires_at=expires,
            user=UserResponse.model_validate(user),
        )

    def me(self, user_id: UUID | None) -> UserResponse:
        if not user_id:
            raise AppError(code="authentication_required", message="请先登录", status_code=401)
        user = self.db.scalar(
            select(AppUser).where(AppUser.id == user_id, AppUser.deleted_at.is_(None))
        )
        if not user:
            raise AppError(code="user_not_found", message="用户不存在", status_code=404)
        return UserResponse.model_validate(user)

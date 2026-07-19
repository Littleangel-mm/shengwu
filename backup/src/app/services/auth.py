import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.db.tables import table
from app.models import AppUser
from app.schemas.auth import TokenResponse, UserLogin, UserRegister, UserResponse

_DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")


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

    @staticmethod
    def _login_attempt_key(email: str, client_host: str) -> str:
        normalized = f"{email.casefold()}\0{client_host.strip().casefold()}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _lock_login_attempt(self, key_hash: str) -> None:
        lock_id = int.from_bytes(bytes.fromhex(key_hash[:16]), byteorder="big", signed=True)
        self.db.scalar(select(func.pg_advisory_xact_lock(lock_id)))

    def _check_login_throttle(self, key_hash: str, now: datetime) -> None:
        attempts = table(self.db, "auth_login_attempts")
        blocked_until = self.db.scalar(
            select(attempts.c.blocked_until).where(attempts.c.key_hash == key_hash)
        )
        if blocked_until is not None and blocked_until > now:
            raise AppError(
                code="login_rate_limited",
                message="登录尝试过多，请稍后再试",
                status_code=429,
                details={"retry_after_seconds": max(1, int((blocked_until - now).total_seconds()))},
            )

    def _record_login_failure(self, key_hash: str, now: datetime) -> None:
        attempts = table(self.db, "auth_login_attempts")
        settings = get_settings()
        row = (
            self.db.execute(
                select(attempts).where(attempts.c.key_hash == key_hash).with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        window = timedelta(minutes=settings.login_attempt_window_minutes)
        if row is None:
            should_reset = True
            failed_count = 1
        else:
            should_reset = row["window_started_at"] + window <= now or (
                row["blocked_until"] is not None and row["blocked_until"] <= now
            )
            failed_count = 1 if should_reset else int(row["failed_count"]) + 1
        blocked_until = (
            now + timedelta(minutes=settings.login_lock_minutes)
            if failed_count >= settings.login_max_failures
            else None
        )
        if row is None:
            self.db.execute(
                insert(attempts).values(
                    key_hash=key_hash,
                    failed_count=failed_count,
                    window_started_at=now,
                    blocked_until=blocked_until,
                    updated_at=now,
                )
            )
        else:
            self.db.execute(
                update(attempts)
                .where(attempts.c.key_hash == key_hash)
                .values(
                    failed_count=failed_count,
                    window_started_at=now if should_reset else row["window_started_at"],
                    blocked_until=blocked_until,
                    updated_at=now,
                )
            )

    def login(self, payload: UserLogin, client_host: str) -> TokenResponse:
        now = datetime.now(UTC)
        key_hash = self._login_attempt_key(payload.email, client_host)
        self._lock_login_attempt(key_hash)
        self._check_login_throttle(key_hash, now)
        user = self.db.scalar(
            select(AppUser).where(
                func.lower(AppUser.email) == payload.email.casefold(),
                AppUser.deleted_at.is_(None),
            )
        )
        password_hash = user.password_hash if user and user.password_hash else _DUMMY_PASSWORD_HASH
        password_valid = verify_password(payload.password, password_hash)
        if not user or not password_valid:
            self._record_login_failure(key_hash, now)
            self.db.commit()
            raise AppError(code="invalid_credentials", message="邮箱或密码错误", status_code=401)
        if user.status != "active":
            raise AppError(code="user_disabled", message="用户已停用", status_code=403)
        attempts = table(self.db, "auth_login_attempts")
        self.db.execute(delete(attempts).where(attempts.c.key_hash == key_hash))
        user.last_login_at = now
        self.db.commit()
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

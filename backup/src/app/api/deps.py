from collections.abc import Generator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import parse_access_token
from app.db.session import SessionLocal
from app.db.tables import table
from app.models import AppUser


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_actor_id(
    authorization: Annotated[str | None, Header()] = None,
    x_actor_id: Annotated[str | None, Header()] = None,
) -> UUID | None:
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not token:
            raise AppError(
                code="invalid_authorization",
                message="Authorization 格式无效",
                status_code=401,
            )
        return parse_access_token(token)
    if not x_actor_id:
        return None
    settings = get_settings()
    if settings.is_production or not settings.allow_actor_header:
        raise AppError(
            code="actor_header_disabled",
            message="当前环境不允许 X-Actor-ID",
            status_code=401,
        )
    try:
        return UUID(x_actor_id)
    except ValueError as exc:
        raise AppError(
            code="invalid_actor_id",
            message="X-Actor-ID 必须是有效的 UUID",
            status_code=400,
        ) from exc


DbSession = Annotated[Session, Depends(get_db)]
ActorId = Annotated[UUID | None, Depends(get_actor_id)]


def get_current_actor_id(db: DbSession, actor_id: ActorId) -> UUID:
    if not actor_id:
        raise AppError(code="authentication_required", message="请先登录", status_code=401)
    user = db.get(AppUser, actor_id)
    if not user or user.deleted_at is not None or user.status != "active":
        raise AppError(code="user_disabled", message="用户不存在或已停用", status_code=403)
    return actor_id


CurrentActorId = Annotated[UUID, Depends(get_current_actor_id)]


def _project_role(
    db: Session, project_id: UUID, actor_id: UUID
) -> tuple[str | None, str | None] | None:
    projects = table(db, "projects")
    project_members = table(db, "project_members")
    organization_members = table(db, "organization_members")
    row = db.execute(
        select(
            project_members.c.role.label("project_role"),
            organization_members.c.role.label("organization_role"),
        )
        .select_from(projects)
        .outerjoin(
            project_members,
            (project_members.c.project_id == projects.c.id)
            & (project_members.c.user_id == actor_id),
        )
        .outerjoin(
            organization_members,
            (organization_members.c.organization_id == projects.c.organization_id)
            & (organization_members.c.user_id == actor_id)
            & (organization_members.c.status == "active"),
        )
        .where(
            projects.c.id == project_id,
            projects.c.deleted_at.is_(None),
            or_(
                project_members.c.user_id.is_not(None), organization_members.c.user_id.is_not(None)
            ),
        )
    ).one_or_none()
    if not row:
        return None
    return row.project_role, row.organization_role


def _organization_role(db: Session, organization_id: UUID, actor_id: UUID) -> str | None:
    organizations = table(db, "organizations")
    organization_members = table(db, "organization_members")
    return db.scalar(
        select(organization_members.c.role)
        .join(
            organizations,
            organizations.c.id == organization_members.c.organization_id,
        )
        .where(
            organizations.c.id == organization_id,
            organizations.c.deleted_at.is_(None),
            organization_members.c.user_id == actor_id,
            organization_members.c.status == "active",
        )
    )


def require_project_member(
    project_id: UUID,
    db: DbSession,
    actor_id: CurrentActorId,
) -> UUID:
    if not _project_role(db, project_id, actor_id):
        # Use 404 so callers cannot enumerate projects outside their tenancy.
        raise AppError(code="project_not_found", message="项目不存在", status_code=404)
    return actor_id


def require_project_editor(
    project_id: UUID,
    db: DbSession,
    actor_id: CurrentActorId,
) -> UUID:
    roles = _project_role(db, project_id, actor_id)
    if not roles:
        raise AppError(code="project_not_found", message="项目不存在", status_code=404)
    project_role, organization_role = roles
    if project_role not in {"owner", "editor"} and organization_role not in {"owner", "admin"}:
        raise AppError(code="project_write_forbidden", message="没有项目写入权限", status_code=403)
    return actor_id


def require_project_access(
    request: Request,
    project_id: UUID,
    db: DbSession,
    actor_id: CurrentActorId,
) -> UUID:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return require_project_member(project_id, db, actor_id)
    return require_project_editor(project_id, db, actor_id)


def require_organization_member(
    organization_id: UUID,
    db: DbSession,
    actor_id: CurrentActorId,
) -> UUID:
    if not _organization_role(db, organization_id, actor_id):
        raise AppError(code="organization_not_found", message="组织不存在", status_code=404)
    return actor_id


def require_organization_admin(
    organization_id: UUID,
    db: DbSession,
    actor_id: CurrentActorId,
) -> UUID:
    role = _organization_role(db, organization_id, actor_id)
    if not role:
        raise AppError(code="organization_not_found", message="组织不存在", status_code=404)
    if role not in {"owner", "admin"}:
        raise AppError(
            code="organization_admin_required",
            message="需要组织管理员权限",
            status_code=403,
        )
    return actor_id


def require_platform_admin(actor_id: CurrentActorId) -> UUID:
    if actor_id not in get_settings().platform_admin_user_id_set:
        raise AppError(
            code="platform_admin_required",
            message="需要平台管理员权限",
            status_code=403,
        )
    return actor_id


def authorize_conversion_rule_write(
    db: DbSession,
    actor_id: CurrentActorId,
    organization_id: UUID | None = None,
) -> UUID:
    if organization_id is None:
        return require_platform_admin(actor_id)
    return require_organization_admin(organization_id, db, actor_id)


ProjectMember = Annotated[UUID, Depends(require_project_member)]
ProjectEditor = Annotated[UUID, Depends(require_project_editor)]
ProjectAccess = Annotated[UUID, Depends(require_project_access)]
OrganizationMember = Annotated[UUID, Depends(require_organization_member)]
OrganizationAdmin = Annotated[UUID, Depends(require_organization_admin)]
PlatformAdmin = Annotated[UUID, Depends(require_platform_admin)]
ConversionRuleAdmin = Annotated[UUID, Depends(authorize_conversion_rule_write)]

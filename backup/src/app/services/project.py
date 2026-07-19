from __future__ import annotations

import builtins
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, literal, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import AppUser, Organization, Project
from app.schemas.project import (
    ProjectCreate,
    ProjectMemberInvite,
    ProjectMemberResponse,
    ProjectMembershipResponse,
    ProjectMemberUpdate,
    ProjectResponse,
    ProjectUpdate,
)
from app.services.audit import AuditService
from app.services.utils import make_slug


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _get_model(self, project_id: UUID) -> Project:
        project = self.db.scalar(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )
        if not project:
            raise AppError(code="project_not_found", message="项目不存在", status_code=404)
        return project

    def create(self, payload: ProjectCreate, actor_id: UUID | None) -> ProjectResponse:
        organization = self.db.scalar(
            select(Organization).where(
                Organization.id == payload.organization_id,
                Organization.deleted_at.is_(None),
            )
        )
        if not organization:
            raise AppError(code="organization_not_found", message="组织不存在", status_code=404)
        members = table(self.db, "organization_members")
        membership = self.db.execute(
            select(members.c.role).where(
                members.c.organization_id == payload.organization_id,
                members.c.user_id == actor_id,
                members.c.status == "active",
            )
        ).scalar_one_or_none()
        if membership not in {"owner", "admin", "member"}:
            raise AppError(code="organization_not_found", message="组织不存在", status_code=404)
        project = Project(
            organization_id=payload.organization_id,
            name=payload.name.strip(),
            slug=payload.slug or make_slug(payload.name, 120),
            description=payload.description,
            research_domain=payload.research_domain,
            default_language=payload.default_language,
            settings=payload.settings,
            created_by=actor_id,
        )
        self.db.add(project)
        try:
            self.db.flush()
            if actor_id and self.db.get(AppUser, actor_id):
                members = table(self.db, "project_members")
                self.db.execute(
                    insert(members).values(
                        project_id=project.id,
                        user_id=actor_id,
                        role="owner",
                        permissions={"all": True},
                    )
                )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AppError(
                code="project_slug_exists", message="该组织内项目标识已存在", status_code=409
            ) from exc
        self.db.refresh(project)
        return ProjectResponse.model_validate(project)

    def list(
        self,
        *,
        organization_id: UUID | None,
        offset: int,
        limit: int,
        actor_id: UUID,
    ) -> tuple[list[ProjectResponse], int]:
        filters: list[Any] = [Project.deleted_at.is_(None)]
        if organization_id:
            filters.append(Project.organization_id == organization_id)
        project_members = table(self.db, "project_members")
        organization_members = table(self.db, "organization_members")
        access = or_(
            project_members.c.user_id == actor_id,
            organization_members.c.user_id == actor_id,
        )
        base = (
            select(Project)
            .outerjoin(
                project_members,
                (project_members.c.project_id == Project.id)
                & (project_members.c.user_id == actor_id),
            )
            .outerjoin(
                organization_members,
                (organization_members.c.organization_id == Project.organization_id)
                & (organization_members.c.user_id == actor_id)
                & (organization_members.c.status == "active"),
            )
            .where(*filters, access)
        )
        total = self.db.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.db.scalars(
            base.distinct().order_by(Project.created_at.desc()).offset(offset).limit(limit)
        ).all()
        return [ProjectResponse.model_validate(row) for row in rows], total

    def get(self, project_id: UUID) -> ProjectResponse:
        return ProjectResponse.model_validate(self._get_model(project_id))

    def update(self, project_id: UUID, payload: ProjectUpdate) -> ProjectResponse:
        project = self._get_model(project_id)
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(project, field, value.strip() if field == "name" and value else value)
        self.db.commit()
        self.db.refresh(project)
        return ProjectResponse.model_validate(project)

    def soft_delete(self, project_id: UUID) -> None:
        project = self._get_model(project_id)
        project.status = "deleted"
        project.deleted_at = datetime.now(UTC)
        self.db.commit()

    def _member_query(self, project_id: UUID):
        members = table(self.db, "project_members")
        return (
            select(
                members.c.id,
                members.c.user_id,
                AppUser.email,
                AppUser.display_name,
                members.c.role,
                literal("active").label("status"),
                members.c.created_at,
            )
            .join(AppUser, AppUser.id == members.c.user_id)
            .where(members.c.project_id == project_id)
        )

    def _member(self, project_id: UUID, user_id: UUID) -> dict:
        members = table(self.db, "project_members")
        row = (
            self.db.execute(
                self._member_query(project_id).where(members.c.user_id == user_id)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise AppError(
                code="project_member_not_found",
                message="项目成员不存在",
                status_code=404,
            )
        return dict(row)

    def list_members(
        self, project_id: UUID, offset: int, limit: int
    ) -> tuple[builtins.list[ProjectMemberResponse], int]:
        members = table(self.db, "project_members")
        total = (
            self.db.scalar(
                select(func.count())
                .select_from(members)
                .where(members.c.project_id == project_id)
            )
            or 0
        )
        rows = (
            self.db.execute(
                self._member_query(project_id)
                .order_by(members.c.created_at, members.c.id)
                .offset(offset)
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return [ProjectMemberResponse.model_validate(row) for row in rows], total

    def invite_member(
        self,
        project_id: UUID,
        payload: ProjectMemberInvite,
        actor_id: UUID,
    ) -> ProjectMemberResponse:
        members = table(self.db, "project_members")
        user = self.db.scalar(
            select(AppUser).where(
                func.lower(AppUser.email) == str(payload.email).casefold(),
                AppUser.status == "active",
                AppUser.deleted_at.is_(None),
            )
        )
        if user is None:
            raise AppError(code="user_not_found", message="用户不存在", status_code=404)
        try:
            member_id = uuid4()
            self.db.execute(
                insert(members).values(
                    id=member_id,
                    project_id=project_id,
                    user_id=user.id,
                    role=payload.role,
                    permissions={},
                )
            )
            AuditService(self.db).record(
                project_id=project_id,
                actor_id=actor_id,
                entity_type="project_member",
                entity_id=member_id,
                action="project_member.invited",
                after={"user_id": str(user.id), "email": user.email, "role": payload.role},
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AppError(
                code="project_member_exists",
                message="用户已是项目成员",
                status_code=409,
            ) from exc
        return ProjectMemberResponse.model_validate(self._member(project_id, user.id))

    def _protect_last_owner(self, project_id: UUID, member: dict) -> None:
        if member["role"] != "owner":
            return
        members = table(self.db, "project_members")
        owner_ids = self.db.scalars(
            select(members.c.id)
            .where(
                members.c.project_id == project_id,
                members.c.role == "owner",
            )
            .with_for_update()
        ).all()
        if len(owner_ids) <= 1:
            raise AppError(
                code="last_project_owner",
                message="项目必须至少保留一名所有者",
                status_code=409,
            )

    def update_member(
        self,
        project_id: UUID,
        user_id: UUID,
        payload: ProjectMemberUpdate,
        actor_id: UUID,
    ) -> ProjectMemberResponse:
        members = table(self.db, "project_members")
        member = self._member(project_id, user_id)
        member_id = member["id"]
        if member["role"] == "owner" and payload.role != "owner":
            self._protect_last_owner(project_id, member)
        self.db.execute(update(members).where(members.c.id == member_id).values(role=payload.role))
        AuditService(self.db).record(
            project_id=project_id,
            actor_id=actor_id,
            entity_type="project_member",
            entity_id=member_id,
            action="project_member.role_updated",
            before={"role": member["role"]},
            after={"role": payload.role},
        )
        self.db.commit()
        return ProjectMemberResponse.model_validate(self._member(project_id, user_id))

    def remove_member(self, project_id: UUID, user_id: UUID, actor_id: UUID) -> None:
        members = table(self.db, "project_members")
        member = self._member(project_id, user_id)
        member_id = member["id"]
        self._protect_last_owner(project_id, member)
        self.db.execute(delete(members).where(members.c.id == member_id))
        AuditService(self.db).record(
            project_id=project_id,
            actor_id=actor_id,
            entity_type="project_member",
            entity_id=member_id,
            action="project_member.removed",
            before={"user_id": str(member["user_id"]), "role": member["role"]},
        )
        self.db.commit()

    def current_membership(
        self, project_id: UUID, actor_id: UUID
    ) -> ProjectMembershipResponse:
        project = self._get_model(project_id)
        project_members = table(self.db, "project_members")
        organization_members = table(self.db, "organization_members")
        row = self.db.execute(
            select(
                project_members.c.role.label("project_role"),
                organization_members.c.role.label("organization_role"),
            )
            .select_from(Project)
            .outerjoin(
                project_members,
                (project_members.c.project_id == Project.id)
                & (project_members.c.user_id == actor_id),
            )
            .outerjoin(
                organization_members,
                (organization_members.c.organization_id == Project.organization_id)
                & (organization_members.c.user_id == actor_id)
                & (organization_members.c.status == "active"),
            )
            .where(Project.id == project_id)
        ).one_or_none()
        if row is None or (row.project_role is None and row.organization_role is None):
            raise AppError(code="project_not_found", message="项目不存在", status_code=404)
        organization_admin = row.organization_role in {"owner", "admin"}
        can_manage_members = row.project_role == "owner" or organization_admin
        can_write = row.project_role in {"owner", "editor"} or organization_admin
        if can_manage_members:
            role = "owner"
        elif can_write:
            role = "editor"
        else:
            role = "viewer"
        return ProjectMembershipResponse(
            project_id=project.id,
            user_id=actor_id,
            role=role,
            project_role=row.project_role,
            organization_role=row.organization_role,
            can_write=can_write,
            can_manage_members=can_manage_members,
        )

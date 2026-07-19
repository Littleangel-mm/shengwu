from __future__ import annotations

import builtins
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import AppUser, Organization
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationMemberInvite,
    OrganizationMemberResponse,
    OrganizationMemberUpdate,
    OrganizationResponse,
)
from app.services.audit import AuditService
from app.services.utils import make_slug


class OrganizationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, payload: OrganizationCreate, actor_id: UUID | None) -> OrganizationResponse:
        organization = Organization(
            name=payload.name.strip(),
            slug=payload.slug or make_slug(payload.name, 100),
            settings=payload.settings,
            created_by=actor_id,
        )
        self.db.add(organization)
        try:
            self.db.flush()
            if actor_id and self.db.get(AppUser, actor_id):
                members = table(self.db, "organization_members")
                self.db.execute(
                    insert(members).values(
                        organization_id=organization.id,
                        user_id=actor_id,
                        role="owner",
                        status="active",
                    )
                )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AppError(
                code="organization_slug_exists",
                message="组织标识已存在",
                status_code=409,
            ) from exc
        self.db.refresh(organization)
        return OrganizationResponse.model_validate(organization)

    def list(
        self, *, actor_id: UUID, offset: int, limit: int
    ) -> tuple[list[OrganizationResponse], int]:
        members = table(self.db, "organization_members")
        where = (
            Organization.deleted_at.is_(None),
            members.c.user_id == actor_id,
            members.c.status == "active",
        )
        total = (
            self.db.scalar(
                select(func.count())
                .select_from(Organization)
                .join(members, members.c.organization_id == Organization.id)
                .where(*where)
            )
            or 0
        )
        rows = self.db.scalars(
            select(Organization)
            .join(members, members.c.organization_id == Organization.id)
            .where(*where)
            .order_by(Organization.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [OrganizationResponse.model_validate(row) for row in rows], total

    def get(self, organization_id: UUID, actor_id: UUID) -> OrganizationResponse:
        members = table(self.db, "organization_members")
        organization = self.db.scalar(
            select(Organization)
            .join(members, members.c.organization_id == Organization.id)
            .where(
                Organization.id == organization_id,
                Organization.deleted_at.is_(None),
                members.c.user_id == actor_id,
                members.c.status == "active",
            )
        )
        if not organization:
            raise AppError(code="organization_not_found", message="组织不存在", status_code=404)
        return OrganizationResponse.model_validate(organization)

    def _member_query(self, organization_id: UUID):
        members = table(self.db, "organization_members")
        return (
            select(
                members.c.id,
                members.c.user_id,
                AppUser.email,
                AppUser.display_name,
                members.c.role,
                members.c.status,
                members.c.joined_at,
            )
            .join(AppUser, AppUser.id == members.c.user_id)
            .where(members.c.organization_id == organization_id)
        )

    def _member(self, organization_id: UUID, user_id: UUID) -> dict:
        members = table(self.db, "organization_members")
        row = (
            self.db.execute(
                self._member_query(organization_id).where(
                    members.c.user_id == user_id,
                    members.c.status == "active",
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise AppError(
                code="organization_member_not_found",
                message="组织成员不存在",
                status_code=404,
            )
        return dict(row)

    def list_members(
        self, organization_id: UUID, offset: int, limit: int
    ) -> tuple[builtins.list[OrganizationMemberResponse], int]:
        members = table(self.db, "organization_members")
        active = (
            members.c.organization_id == organization_id,
            members.c.status == "active",
        )
        total = self.db.scalar(select(func.count()).select_from(members).where(*active)) or 0
        rows = (
            self.db.execute(
                self._member_query(organization_id)
                .where(members.c.status == "active")
                .order_by(members.c.joined_at, members.c.id)
                .offset(offset)
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return [OrganizationMemberResponse.model_validate(row) for row in rows], total

    def invite_member(
        self,
        organization_id: UUID,
        payload: OrganizationMemberInvite,
        actor_id: UUID,
    ) -> OrganizationMemberResponse:
        members = table(self.db, "organization_members")
        user = self.db.scalar(
            select(AppUser).where(
                func.lower(AppUser.email) == str(payload.email).casefold(),
                AppUser.status == "active",
                AppUser.deleted_at.is_(None),
            )
        )
        if user is None:
            raise AppError(code="user_not_found", message="用户不存在", status_code=404)
        existing = (
            self.db.execute(
                select(members)
                .where(
                    members.c.organization_id == organization_id,
                    members.c.user_id == user.id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None and existing["status"] == "active":
            raise AppError(
                code="organization_member_exists",
                message="用户已是组织成员",
                status_code=409,
            )
        try:
            if existing is None:
                member_id = uuid4()
                self.db.execute(
                    insert(members).values(
                        id=member_id,
                        organization_id=organization_id,
                        user_id=user.id,
                        role=payload.role,
                        status="active",
                    )
                )
            else:
                member_id = existing["id"]
                self.db.execute(
                    update(members)
                    .where(members.c.id == member_id)
                    .values(role=payload.role, status="active", joined_at=func.now())
                )
            AuditService(self.db).record(
                organization_id=organization_id,
                actor_id=actor_id,
                entity_type="organization_member",
                entity_id=member_id,
                action="organization_member.invited",
                after={"user_id": str(user.id), "email": user.email, "role": payload.role},
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AppError(
                code="organization_member_exists",
                message="用户已是组织成员",
                status_code=409,
            ) from exc
        return OrganizationMemberResponse.model_validate(
            self._member(organization_id, user.id)
        )

    def _protect_last_owner(self, organization_id: UUID, member: dict) -> None:
        if member["role"] != "owner":
            return
        members = table(self.db, "organization_members")
        owner_ids = self.db.scalars(
            select(members.c.id)
            .where(
                members.c.organization_id == organization_id,
                members.c.role == "owner",
                members.c.status == "active",
            )
            .with_for_update()
        ).all()
        if len(owner_ids) <= 1:
            raise AppError(
                code="last_organization_owner",
                message="组织必须至少保留一名所有者",
                status_code=409,
            )

    def update_member(
        self,
        organization_id: UUID,
        user_id: UUID,
        payload: OrganizationMemberUpdate,
        actor_id: UUID,
    ) -> OrganizationMemberResponse:
        members = table(self.db, "organization_members")
        member = self._member(organization_id, user_id)
        member_id = member["id"]
        if member["role"] == "owner" and payload.role != "owner":
            self._protect_last_owner(organization_id, member)
        self.db.execute(
            update(members).where(members.c.id == member_id).values(role=payload.role)
        )
        AuditService(self.db).record(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="organization_member",
            entity_id=member_id,
            action="organization_member.role_updated",
            before={"role": member["role"]},
            after={"role": payload.role},
        )
        self.db.commit()
        return OrganizationMemberResponse.model_validate(
            self._member(organization_id, user_id)
        )

    def remove_member(self, organization_id: UUID, user_id: UUID, actor_id: UUID) -> None:
        members = table(self.db, "organization_members")
        member = self._member(organization_id, user_id)
        member_id = member["id"]
        self._protect_last_owner(organization_id, member)
        self.db.execute(
            update(members).where(members.c.id == member_id).values(status="removed")
        )
        AuditService(self.db).record(
            organization_id=organization_id,
            actor_id=actor_id,
            entity_type="organization_member",
            entity_id=member_id,
            action="organization_member.removed",
            before={"user_id": str(member["user_id"]), "role": member["role"]},
        )
        self.db.commit()

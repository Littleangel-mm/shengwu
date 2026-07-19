from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import AppUser, Organization
from app.schemas.organization import OrganizationCreate, OrganizationResponse
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

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import AppUser, Organization, Project
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
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

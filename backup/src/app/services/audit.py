from typing import Any
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.tables import table


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        project_id: UUID,
        actor_id: UUID | None,
        entity_type: str,
        entity_id: UUID | None,
        action: str,
        before: Any = None,
        after: Any = None,
        reason: str | None = None,
    ) -> None:
        projects = table(self.db, "projects")
        logs = table(self.db, "audit_logs")
        organization_id = self.db.scalar(
            select(projects.c.organization_id).where(projects.c.id == project_id)
        )
        if not organization_id:
            return
        self.db.execute(
            insert(logs).values(
                organization_id=organization_id,
                project_id=project_id,
                actor_id=actor_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                before_value=before,
                after_value=after,
                reason=reason,
            )
        )

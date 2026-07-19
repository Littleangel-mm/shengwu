from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.schemas.system import (
    ConversionRuleCreate,
    ConvertValueRequest,
    ExternalServiceCreate,
    UnitCreate,
)


class SystemService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @classmethod
    def _redact_sensitive_configuration(cls, value: Any) -> Any:
        if isinstance(value, dict):
            redacted = {}
            for key, item in value.items():
                normalized = str(key).casefold().replace("-", "_")
                if any(
                    marker in normalized
                    for marker in (
                        "secret",
                        "password",
                        "token",
                        "api_key",
                        "apikey",
                        "credential",
                        "authorization",
                        "private_key",
                    )
                ):
                    redacted[key] = "***"
                else:
                    redacted[key] = cls._redact_sensitive_configuration(item)
            return redacted
        if isinstance(value, list):
            return [cls._redact_sensitive_configuration(item) for item in value]
        return value

    def list_units(self) -> list[dict]:
        units = table(self.db, "units")
        return [
            dict(row)
            for row in self.db.execute(
                select(units)
                .where(units.c.is_active.is_(True))
                .order_by(units.c.dimension, units.c.code)
            ).mappings()
        ]

    def create_unit(self, payload: UnitCreate) -> dict:
        units = table(self.db, "units")
        row = (
            self.db.execute(
                insert(units)
                .values(
                    code=payload.code,
                    symbol=payload.symbol,
                    name=payload.name,
                    dimension=payload.dimension,
                    system=payload.system,
                    aliases=payload.aliases,
                    metadata={},
                )
                .returning(units)
            )
            .mappings()
            .one()
        )
        self.db.commit()
        return dict(row)

    def create_conversion_rule(
        self, organization_id: UUID | None, payload: ConversionRuleCreate, actor_id: UUID
    ) -> dict:
        rules = table(self.db, "unit_conversion_rules")
        row = (
            self.db.execute(
                insert(rules)
                .values(
                    organization_id=organization_id,
                    source_unit_id=payload.source_unit_id,
                    target_unit_id=payload.target_unit_id,
                    rule_name=payload.rule_name,
                    multiplier=payload.multiplier,
                    offset_value=payload.offset_value,
                    formula_expression=payload.formula_expression,
                    context_requirements=payload.context_requirements,
                    requires_confirmation=payload.requires_confirmation,
                    created_by=actor_id,
                )
                .returning(rules)
            )
            .mappings()
            .one()
        )
        self.db.commit()
        return dict(row)

    def convert(self, payload: ConvertValueRequest, actor_id: UUID) -> dict:
        rules = table(self.db, "unit_conversion_rules")
        row = (
            self.db.execute(
                select(rules).where(rules.c.id == payload.rule_id, rules.c.is_active.is_(True))
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise AppError(
                code="conversion_rule_not_found", message="换算规则不存在", status_code=404
            )
        if row["organization_id"] is not None:
            members = table(self.db, "organization_members")
            membership = self.db.scalar(
                select(members.c.id).where(
                    members.c.organization_id == row["organization_id"],
                    members.c.user_id == actor_id,
                    members.c.status == "active",
                )
            )
            if not membership:
                raise AppError(
                    code="conversion_rule_not_found",
                    message="换算规则不存在",
                    status_code=404,
                )
        if row["requires_confirmation"] and not payload.confirmed:
            raise AppError(
                code="conversion_requires_confirmation",
                message="该换算需要人工确认",
                status_code=409,
            )
        if row["multiplier"] is None:
            raise AppError(
                code="formula_conversion_not_executable",
                message="复杂公式换算需要领域适配器",
                status_code=422,
            )
        result = payload.value * float(row["multiplier"]) + float(row["offset_value"] or 0)
        return {
            "source_value": payload.value,
            "target_value": result,
            "rule_id": payload.rule_id,
            "target_unit_id": row["target_unit_id"],
        }

    def list_audit(self, project_id: UUID, offset: int, limit: int) -> tuple[list[dict], int]:
        logs = table(self.db, "audit_logs")
        total = (
            self.db.scalar(
                select(func.count()).select_from(logs).where(logs.c.project_id == project_id)
            )
            or 0
        )
        rows = (
            self.db.execute(
                select(logs)
                .where(logs.c.project_id == project_id)
                .order_by(logs.c.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows], total

    def create_external_service(
        self,
        organization_id: UUID,
        project_id: UUID | None,
        payload: ExternalServiceCreate,
        actor_id: UUID,
    ) -> dict:
        self._validate_project_scope(organization_id, project_id)
        configs = table(self.db, "external_service_configs")
        row = (
            self.db.execute(
                insert(configs)
                .values(
                    organization_id=organization_id,
                    project_id=project_id,
                    service_type=payload.service_type,
                    provider=payload.provider,
                    name=payload.name,
                    secret_reference=payload.secret_reference,
                    endpoint_url=payload.endpoint_url,
                    configuration=payload.configuration,
                    created_by=actor_id,
                )
                .returning(configs)
            )
            .mappings()
            .one()
        )
        self.db.commit()
        result = dict(row)
        result["secret_reference"] = "***" if result.get("secret_reference") else None
        result["configuration"] = self._redact_sensitive_configuration(
            result.get("configuration", {})
        )
        return result

    def list_external_services(self, organization_id: UUID, project_id: UUID | None) -> list[dict]:
        self._validate_project_scope(organization_id, project_id)
        configs = table(self.db, "external_service_configs")
        filters = [configs.c.organization_id == organization_id]
        if project_id:
            filters.append(configs.c.project_id == project_id)
        rows = [
            dict(row)
            for row in self.db.execute(
                select(configs).where(*filters).order_by(configs.c.created_at.desc())
            ).mappings()
        ]
        for row in rows:
            row["secret_reference"] = "***" if row.get("secret_reference") else None
            row["configuration"] = self._redact_sensitive_configuration(
                row.get("configuration", {})
            )
        return rows

    def _validate_project_scope(self, organization_id: UUID, project_id: UUID | None) -> None:
        if project_id is None:
            return
        projects = table(self.db, "projects")
        exists = self.db.scalar(
            select(projects.c.id).where(
                projects.c.id == project_id,
                projects.c.organization_id == organization_id,
                projects.c.deleted_at.is_(None),
            )
        )
        if not exists:
            raise AppError(code="project_not_found", message="项目不存在", status_code=404)

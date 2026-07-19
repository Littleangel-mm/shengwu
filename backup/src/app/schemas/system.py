from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class UnitCreate(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    symbol: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    dimension: str = Field(min_length=1, max_length=100)
    system: str | None = Field(default=None, max_length=50)
    aliases: list[str] = Field(default_factory=list)


class ConversionRuleCreate(BaseModel):
    source_unit_id: UUID
    target_unit_id: UUID
    rule_name: str = Field(min_length=1, max_length=200)
    multiplier: float | None = None
    offset_value: float | None = None
    formula_expression: str | None = None
    requires_confirmation: bool = False
    context_requirements: dict[str, Any] = Field(default_factory=dict)


class ConvertValueRequest(BaseModel):
    rule_id: UUID
    value: float
    confirmed: bool = False


class ExternalServiceCreate(BaseModel):
    service_type: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    secret_reference: str | None = None
    endpoint_url: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)

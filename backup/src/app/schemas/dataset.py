from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DatasetBuildCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    description: str | None = None
    extraction_run_id: UUID
    include_review_statuses: list[str] = Field(
        default_factory=lambda: ["pending", "confirmed", "modified"]
    )


class DatasetFieldCreate(BaseModel):
    field_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_\-]+$")
    display_name: str = Field(min_length=1, max_length=240)
    data_type: Literal["text", "number", "boolean", "date", "json", "range"] = "text"
    semantic_role: str = Field(default="feature", max_length=32)
    unit_id: UUID | None = None
    is_required: bool = False


class DatasetRowCreate(BaseModel):
    row_key: str = Field(min_length=1, max_length=255)
    source_document_id: UUID | None = None
    source_document_version_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetCellUpdate(BaseModel):
    value_text: str | None = None
    value_number: float | None = None
    value_boolean: bool | None = None
    value_date: str | None = None
    value_json: Any | None = None
    normalized_value: dict[str, Any] | None = None
    ml_value: dict[str, Any] | None = None
    unit_id: UUID | None = None
    review_status: Literal["pending", "confirmed", "modified", "deleted", "doubtful"] | None = None
    is_missing: bool | None = None
    notes: str | None = None


class DatasetVersionClone(BaseModel):
    change_summary: str = Field(min_length=1, max_length=2000)

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskAccepted(BaseModel):
    resource_id: UUID
    job_id: UUID
    status: str = "queued"


class SearchCreate(BaseModel):
    name: str | None = Field(default=None, max_length=240)
    terms: list[str] = Field(min_length=1, max_length=30)
    logic_operator: Literal["AND", "OR"] = "AND"
    match_scope: Literal["evidence_block", "page", "document"] = "evidence_block"
    search_mode: Literal["exact", "fuzzy", "semantic", "hybrid"] = "hybrid"
    fuzzy_threshold: int = Field(default=82, ge=50, le=100)
    semantic_threshold: float = Field(default=0.18, ge=0, le=1)


class SearchResultReview(BaseModel):
    is_included: bool
    review_status: Literal["pending", "confirmed", "excluded"]


class TermCategoryCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class TermCategoryUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class TermCreate(BaseModel):
    category_id: UUID
    canonical_name: str = Field(min_length=1, max_length=240)
    definition: str | None = None
    language: str | None = Field(default=None, max_length=20)
    data_type: str | None = Field(default=None, max_length=32)
    semantic_role: str | None = Field(default=None, max_length=32)
    status: str = "confirmed"
    is_selected: bool = True
    aliases: list[str] = Field(default_factory=list)


class TermUpdate(BaseModel):
    category_id: UUID | None = None
    canonical_name: str | None = Field(default=None, min_length=1, max_length=240)
    definition: str | None = None
    language: str | None = Field(default=None, max_length=20)
    data_type: str | None = Field(default=None, max_length=32)
    semantic_role: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)
    is_selected: bool | None = None
    include_in_model: bool | None = None
    include_in_score: bool | None = None
    indicator_direction: str | None = Field(default=None, max_length=32)
    aliases: list[str] | None = None


class TermMerge(BaseModel):
    target_term_id: UUID
    source_term_ids: list[UUID] = Field(min_length=1, max_length=100)
    reason: str | None = Field(default=None, max_length=1000)


class TermSplitItem(BaseModel):
    category_id: UUID
    canonical_name: str = Field(min_length=1, max_length=240)
    aliases: list[str] = Field(default_factory=list)
    semantic_role: str | None = Field(default=None, max_length=32)
    data_type: str | None = Field(default=None, max_length=32)


class TermSplit(BaseModel):
    children: list[TermSplitItem] = Field(min_length=2, max_length=20)
    reason: str | None = Field(default=None, max_length=1000)


class TermDiscoveryCreate(BaseModel):
    search_run_id: UUID
    min_occurrences: int = Field(default=2, ge=2, le=100)
    max_candidates: int = Field(default=500, ge=10, le=5000)


class FieldDiscoveryCreate(BaseModel):
    search_run_id: UUID | None = None
    min_documents: int = Field(default=1, ge=1, le=100)
    max_candidates: int = Field(default=200, ge=10, le=2000)
    use_llm: bool = True


class FieldDefinitionInput(BaseModel):
    field_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_\-]+$")
    display_name: str = Field(min_length=1, max_length=240)
    source_term_id: UUID | None = None
    category_code: str | None = Field(default=None, max_length=100)
    semantic_role: str = Field(default="feature", max_length=32)
    data_type: Literal["text", "number", "boolean", "date", "category", "range"] = "text"
    preferred_unit_id: UUID | None = None
    indicator_direction: str | None = Field(default=None, max_length=32)
    is_required: bool = False
    is_identifier: bool = False
    include_in_model: bool = False
    include_in_score: bool = False
    extraction_config: dict[str, Any] = Field(default_factory=dict)
    validation_rules: dict[str, Any] = Field(default_factory=dict)


class FieldSchemaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    source_search_run_id: UUID | None = None
    fields: list[FieldDefinitionInput] = Field(min_length=1, max_length=500)
    settings: dict[str, Any] = Field(default_factory=dict)


class FieldSchemaUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    settings: dict[str, Any]
    fields: list[FieldDefinitionInput] = Field(min_length=1, max_length=500)


class CandidateFieldInput(BaseModel):
    term_id: UUID
    field_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_\-]+$")
    display_name: str = Field(min_length=1, max_length=240)
    semantic_role: str = Field(default="feature", max_length=32)
    data_type: Literal["text", "number", "boolean", "date", "category", "range"] = "number"
    is_identifier: bool = False
    include_in_model: bool = True
    include_in_score: bool = False


class FieldSchemaFromCandidates(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    candidates: list[CandidateFieldInput] = Field(min_length=1, max_length=500)


class ExtractionCreate(BaseModel):
    name: str | None = Field(default=None, max_length=240)
    field_schema_id: UUID
    search_run_id: UUID | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)


class ExtractionRecordReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_status: Literal["confirmed", "modified", "doubtful", "excluded"]
    normalized_value: dict[str, Any] | None = None
    ml_value: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=5000)


class ExtractionRunSummary(BaseModel):
    extraction_run_id: UUID
    status: str
    total_records: int
    field_count: int
    document_count: int
    review_status_counts: dict[str, int]


class TranslationCreate(BaseModel):
    target_language: str = Field(default="zh-CN", min_length=2, max_length=20)
    overwrite: bool = False

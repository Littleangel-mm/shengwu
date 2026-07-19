from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UploadResult(BaseModel):
    filename: str
    status: str
    message: str | None = None
    duplicate_file_id: UUID | None = None
    file_id: UUID | None = None
    document_id: UUID | None = None
    document_version_id: UUID | None = None
    job_id: UUID | None = None


class UploadBatchResponse(BaseModel):
    project_id: UUID
    total: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    duplicated: int = Field(ge=0)
    failed: int = Field(ge=0)
    items: list[UploadResult]


class DocumentResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str | None
    document_type: str
    language: str | None
    status: str
    version_id: UUID
    version_no: int
    parse_status: str
    page_count: int | None
    original_name: str
    byte_size: int
    created_at: datetime

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    document_version_id: UUID | None
    job_type: str
    status: str
    progress_percent: Decimal
    current_stage: str | None
    result_summary: dict[str, Any]
    error_code: str | None
    error_message: str | None
    retry_count: int
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime

from uuid import UUID

from pydantic import BaseModel, Field


class ReportCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    dataset_version_id: UUID
    ml_run_id: UUID | None = None
    optimization_run_id: UUID | None = None
    configuration: dict = Field(default_factory=dict)

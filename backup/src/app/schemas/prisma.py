from pydantic import BaseModel, Field


class PrismaExclusionReason(BaseModel):
    reason: str = Field(min_length=1, max_length=200)
    count: int = Field(default=0, ge=0)


class PrismaFlowUpdate(BaseModel):
    identified_databases: int = Field(default=0, ge=0)
    identified_registers: int = Field(default=0, ge=0)
    duplicates_removed: int = Field(default=0, ge=0)
    records_screened: int = Field(default=0, ge=0)
    records_excluded: int = Field(default=0, ge=0)
    reports_sought: int = Field(default=0, ge=0)
    reports_not_retrieved: int = Field(default=0, ge=0)
    reports_assessed: int = Field(default=0, ge=0)
    studies_included: int = Field(default=0, ge=0)
    reports_excluded: list[PrismaExclusionReason] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=2000)

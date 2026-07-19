from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ProjectCreate(BaseModel):
    organization_id: UUID
    name: str = Field(min_length=1, max_length=240)
    slug: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    research_domain: str | None = Field(default=None, max_length=200)
    default_language: str = Field(default="zh-CN", min_length=2, max_length=20)
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    research_domain: str | None = Field(default=None, max_length=200)
    default_language: str | None = Field(default=None, min_length=2, max_length=20)
    status: str | None = Field(default=None, min_length=1, max_length=32)
    settings: dict[str, Any] | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str | None
    research_domain: str | None
    default_language: str
    status: str
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


ProjectRole = Literal["owner", "editor", "viewer"]


class ProjectMemberInvite(BaseModel):
    email: EmailStr
    role: ProjectRole = "viewer"


class ProjectMemberUpdate(BaseModel):
    role: ProjectRole


class ProjectMemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    display_name: str
    role: ProjectRole
    status: str
    created_at: datetime


class ProjectMembershipResponse(BaseModel):
    project_id: UUID
    user_id: UUID
    role: ProjectRole
    project_role: ProjectRole | None
    organization_role: str | None
    can_write: bool
    can_manage_members: bool

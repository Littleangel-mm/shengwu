from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    settings: dict[str, Any] = Field(default_factory=dict)


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    status: str
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


OrganizationRole = Literal["owner", "admin", "member"]


class OrganizationMemberInvite(BaseModel):
    email: EmailStr
    role: OrganizationRole = "member"


class OrganizationMemberUpdate(BaseModel):
    role: OrganizationRole


class OrganizationMemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    display_name: str
    role: OrganizationRole
    status: str
    joined_at: datetime

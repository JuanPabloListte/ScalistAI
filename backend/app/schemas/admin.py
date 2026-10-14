from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class JobRoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_default: bool = False


class JobRoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OrgUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    is_superadmin: bool
    created_at: datetime
    job_roles: list[JobRoleRead] = Field(default_factory=list)


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subscription_status: str
    stripe_customer_id: str | None
    created_at: datetime
    updated_at: datetime


class OrganizationListItem(OrganizationRead):
    user_count: int
    project_count: int


class OrganizationDetail(OrganizationRead):
    users: list[OrgUserRead]


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    subscription_status: str = Field(default="active", max_length=64)
    admin_email: EmailStr | None = None
    admin_password: str | None = Field(default=None, min_length=8, max_length=128)


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    subscription_status: str | None = Field(default=None, max_length=64)


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="member", pattern="^(admin|member)$")
    job_role_ids: list[int] = Field(default_factory=list)


class AdminUserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: str | None = Field(default=None, pattern="^(admin|member)$")
    # None = no tocar; lista (incluso vacía) = reemplazar asignación
    job_role_ids: list[int] | None = None

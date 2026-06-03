from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    is_superadmin: bool
    created_at: datetime


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(None, min_length=8, max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


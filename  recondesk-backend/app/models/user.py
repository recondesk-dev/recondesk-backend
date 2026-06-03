from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.base import StrictModel


# ── Legacy models (kept) ────────────────────────────────────────────────────

class UserBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: Optional[str] = Field(default=None, max_length=255)
    company_name: Optional[str] = Field(default=None, max_length=255)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=256)


class UserUpdate(StrictModel):
    full_name: Optional[str] = Field(default=None, max_length=255)
    company_name: Optional[str] = Field(default=None, max_length=255)
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    id: UUID
    is_active: bool
    created_at: datetime
    plan: Optional[str] = "free"

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(StrictModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ── API auth models ─────────────────────────────────────────────────────────


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class SignupRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    full_name: str = Field(max_length=255)
    firm_name: str = Field(max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)


class SignupResponse(StrictModel):
    user_id: str
    message: str


class LoginResponse(StrictModel):
    access_token: str
    token_type: str = "bearer"
    user: dict
    role: str


class UserProfileResponse(StrictModel):
    id: str
    email: Optional[str] = None
    full_name: Optional[str] = Field(default=None, max_length=255)
    firm_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    role: str = "staff"
    is_active: bool = True
    created_at: Optional[datetime] = None
    plan: Optional[str] = None
    runs_used: Optional[int] = None
    runs_limit: Optional[int] = None
    free_runs_remaining: Optional[int] = None
    runs_balance: Optional[int] = None
    firm_city: Optional[str] = Field(default=None, max_length=128)
    icai_membership_number: Optional[str] = Field(default=None, max_length=64)
    firm_gstin: Optional[str] = Field(default=None, max_length=15)
    onboarding_completed: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


class ProfileUpdateRequest(StrictModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=32)
    firm_name: Optional[str] = Field(default=None, max_length=255)
    icai_membership_number: Optional[str] = Field(default=None, max_length=64)
    firm_gstin: Optional[str] = Field(default=None, max_length=15)
    firm_city: Optional[str] = Field(default=None, max_length=128)

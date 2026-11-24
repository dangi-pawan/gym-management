from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.features.users.schemas import UserResponse


class LoginRequest(BaseModel):
    organization_slug: str = Field(min_length=1, max_length=180)
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("organization_slug", mode="before")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class RegisterOrganizationRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=150)
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

    @field_validator("organization_name", "full_name")
    @classmethod
    def strip_names(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty")
        return value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class LoginResponse(BaseModel):
    csrf_token: str
    access_expires_at: datetime


class RefreshResponse(BaseModel):
    csrf_token: str
    access_expires_at: datetime

class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class ForgotPasswordRequest(BaseModel):
    organization_slug: str = Field(min_length=1, max_length=180)
    email: EmailStr

    @field_validator("organization_slug", mode="before")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)


class GymRoleInfo(BaseModel):
    gym_id: int
    role: str


class AuthenticatedUserResponse(UserResponse):
    organization_role: str | None
    gym_roles: list[GymRoleInfo]

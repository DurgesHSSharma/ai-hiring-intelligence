from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.enums import UserRole

# bcrypt truncates the input at 72 BYTES, not characters — a str.Field
# max_length counts characters, so a password full of multibyte UTF-8 would
# pass a character-count bound and then get silently truncated by bcrypt.
# Checked on the encoded form instead, shared by both directions below.
_BCRYPT_MAX_BYTES = 72


def _validate_bcrypt_byte_length(password: str) -> str:
    if len(password.encode("utf-8")) > _BCRYPT_MAX_BYTES:
        raise ValueError(f"Password must be at most {_BCRYPT_MAX_BYTES} bytes when UTF-8 encoded.")
    return password


class UserCreate(BaseModel):
    # extra="forbid": role is deliberately not a field here (see auth_service.register
    # — every registration is hardcoded to recruiter). Rejecting unknown keys outright
    # means a client sending "role": "admin" gets a clear 422, not silent acceptance of
    # an unrecognised privilege field with no signal anything was wrong.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def _password_fits_bcrypt(cls, v: str) -> str:
        return _validate_bcrypt_byte_length(v)


class UserLogin(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def _password_fits_bcrypt(cls, v: str) -> str:
        return _validate_bcrypt_byte_length(v)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: UserRole
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

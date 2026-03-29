"""Authentication request/response Pydantic models."""

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=256)
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    username: str
    role: str
    is_active: bool
    created_at: str


class APIKeyCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = ""


class APIKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key_prefix: str
    name: str
    is_active: bool
    last_used_at: str | None
    created_at: str


class APIKeyCreatedResponse(APIKeyResponse):
    key: str  # Only returned once on creation

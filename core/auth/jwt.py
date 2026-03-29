"""JWT token creation and validation."""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from core.auth.config import auth_settings


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=auth_settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc), "type": "access"})
    return jwt.encode(to_encode, auth_settings.get_secret_key(), algorithm=auth_settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> tuple[str, str]:
    """Create a refresh token. Returns (token_string, token_id).

    token_id is stored in the database for revocation tracking.
    """
    token_id = secrets.token_urlsafe(32)
    expire = datetime.now(timezone.utc) + timedelta(days=auth_settings.refresh_token_expire_days)
    payload = {"sub": user_id, "token_id": token_id, "exp": expire, "type": "refresh"}
    token = jwt.encode(payload, auth_settings.get_secret_key(), algorithm=auth_settings.jwt_algorithm)
    return token, token_id


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises jwt.InvalidTokenError on failure."""
    return jwt.decode(
        token, auth_settings.get_secret_key(), algorithms=[auth_settings.jwt_algorithm]
    )

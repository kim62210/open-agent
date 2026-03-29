"""FastAPI auth dependencies for route protection."""

import hashlib
from datetime import datetime, timezone
from typing import Annotated

import jwt as pyjwt
import structlog
from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy import select

from core.db.engine import async_session_factory

logger = structlog.get_logger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    api_key: Annotated[str | None, Depends(api_key_header)] = None,
) -> dict:
    """Extract and validate current user from JWT or API key.

    Returns a user dict with id, email, role, etc.
    Raises 401 if no valid credentials found.
    """
    if token:
        return await _validate_jwt(token)
    if api_key:
        return await _validate_api_key(api_key)
    raise HTTPException(status_code=401, detail="Authentication required")


async def _validate_jwt(token: str) -> dict:
    """Validate a JWT access token and return user info."""
    from core.auth.jwt import decode_token
    from core.db.models.user import UserORM

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        async with async_session_factory() as session:
            user = await session.get(UserORM, user_id)
            if not user or not user.is_active:
                raise HTTPException(status_code=401, detail="User not found or inactive")
            return {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "role": user.role,
            }
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired") from None
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token") from None


async def _validate_api_key(key: str) -> dict:
    """Validate an API key and return user info."""
    from core.db.models.user import APIKeyORM, UserORM

    key_hash = hashlib.sha256(key.encode()).hexdigest()
    async with async_session_factory() as session:
        result = await session.execute(
            select(APIKeyORM).where(APIKeyORM.key_hash == key_hash, APIKeyORM.is_active.is_(True))
        )
        api_key_orm = result.scalar_one_or_none()
        if not api_key_orm:
            raise HTTPException(status_code=401, detail="Invalid API key")
        user = await session.get(UserORM, api_key_orm.user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or inactive")
        api_key_orm.last_used_at = datetime.now(timezone.utc).isoformat()
        await session.commit()
        return {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "role": user.role,
        }


class RoleChecker:
    """Dependency that checks if user has required role."""

    def __init__(self, allowed_roles: list[str]) -> None:
        self.allowed_roles = allowed_roles

    async def __call__(
        self, current_user: Annotated[dict, Depends(get_current_user)]
    ) -> dict:
        if current_user["role"] not in self.allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user


require_admin = RoleChecker(["admin"])
require_user = RoleChecker(["admin", "user"])
require_any = RoleChecker(["admin", "user", "viewer"])

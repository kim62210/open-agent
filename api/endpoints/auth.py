"""Authentication API endpoints."""

from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user, require_admin, require_user
from core.auth.rate_limit import limiter
from core.auth.service import AuthService
from core.db.engine import get_session
from core.exceptions import AlreadyExistsError, NotFoundError, PermissionDeniedError
from models.auth import (
    APIKeyCreateRequest,
    APIKeyCreatedResponse,
    APIKeyResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# -- Request models for admin endpoints (not in models/auth.py) --


class UpdateRoleRequest(BaseModel):
    role: str = Field(pattern=r"^(admin|user|viewer)$")


class UpdateActiveRequest(BaseModel):
    is_active: bool


# -- Helper: build AuthService from session dependency --


def _auth_service(session: AsyncSession) -> AuthService:
    return AuthService(session)


# ── Public endpoints (rate-limited) ──


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    """Create a new user account."""
    try:
        result = await _auth_service(session).register(
            email=body.email, username=body.username, password=body.password
        )
        return UserResponse(**result)
    except AlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    """Authenticate and return access + refresh tokens."""
    try:
        result = await _auth_service(session).login(email=body.email, password=body.password)
        return TokenResponse(**result)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        ) from None
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh(
    request: Request,
    body: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    """Exchange a valid refresh token for a new token pair."""
    try:
        result = await _auth_service(session).refresh_token(body.refresh_token)
        return TokenResponse(**result)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


# ── Authenticated endpoints ──


@router.post("/logout")
async def logout(
    body: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Revoke a refresh token (logout)."""
    import jwt as pyjwt

    from core.auth.jwt import decode_token

    try:
        payload = decode_token(body.refresh_token)
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid refresh token"
        ) from None

    token_id = payload.get("token_id")
    if not token_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid refresh token payload"
        )

    try:
        await _auth_service(session).revoke_refresh_token(token_id)
    except NotFoundError:
        pass  # Already revoked or expired — treat as success
    return {"status": "ok"}


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[dict, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    """Return the currently authenticated user's profile."""
    from core.db.repositories.user_repo import UserRepository

    user = await UserRepository(session).get_by_id(current_user["id"])
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


# ── API key management ──


@router.post("/api-keys", response_model=APIKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: APIKeyCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[dict, Depends(require_user)],
) -> APIKeyCreatedResponse:
    """Create a new API key. The plaintext key is shown only once."""
    result = await _auth_service(session).create_api_key(
        user_id=current_user["id"], name=body.name
    )
    return APIKeyCreatedResponse(**result)


@router.get("/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[dict, Depends(require_user)],
) -> list[APIKeyResponse]:
    """List all API keys for the authenticated user (no plaintext keys)."""
    results = await _auth_service(session).list_api_keys(current_user["id"])
    return [APIKeyResponse(**r) for r in results]


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[dict, Depends(require_user)],
) -> dict:
    """Revoke an API key."""
    try:
        await _auth_service(session).revoke_api_key(key_id=key_id, user_id=current_user["id"])
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return {"status": "revoked"}


# ── Admin endpoints ──


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[dict, Depends(require_admin)],
) -> list[UserResponse]:
    """List all users (admin only)."""
    from core.db.repositories.user_repo import UserRepository

    users = await UserRepository(session).get_all()
    return [
        UserResponse(
            id=u.id,
            email=u.email,
            username=u.username,
            role=u.role,
            is_active=u.is_active,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.patch("/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: str,
    body: UpdateRoleRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[dict, Depends(require_admin)],
) -> UserResponse:
    """Change a user's role (admin only)."""
    from core.db.repositories.user_repo import UserRepository

    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.role = body.role
    user.updated_at = datetime.now(timezone.utc).isoformat()
    await session.commit()

    logger.info("user_role_updated", user_id=user_id, new_role=body.role)
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.patch("/users/{user_id}/active", response_model=UserResponse)
async def toggle_user_active(
    user_id: str,
    body: UpdateActiveRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[dict, Depends(require_admin)],
) -> UserResponse:
    """Toggle a user's active status (admin only)."""
    from core.db.repositories.user_repo import UserRepository

    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = body.is_active
    user.updated_at = datetime.now(timezone.utc).isoformat()
    await session.commit()

    logger.info("user_active_toggled", user_id=user_id, is_active=body.is_active)
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )

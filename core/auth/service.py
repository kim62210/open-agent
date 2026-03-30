"""Authentication service — register, login, refresh, API key management."""

import hashlib
import secrets
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.config import auth_settings
from core.auth.jwt import create_access_token, create_refresh_token, decode_token
from core.auth.password import hash_password, verify_password
from core.db.repositories.user_repo import APIKeyRepository, RefreshTokenRepository, UserRepository
from core.exceptions import AlreadyExistsError, NotFoundError, PermissionDeniedError

logger = structlog.get_logger(__name__)


class AuthService:
    """Business logic for authentication operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repo = UserRepository(session)
        self.token_repo = RefreshTokenRepository(session)
        self.api_key_repo = APIKeyRepository(session)

    async def register(self, email: str, username: str, password: str) -> dict:
        """Register a new user. First user becomes admin if auto_admin_first_user is enabled."""
        if not auth_settings.registration_enabled:
            raise PermissionDeniedError("Registration is currently disabled")

        if await self.user_repo.get_by_email(email):
            raise AlreadyExistsError(f"Email already registered: {email}")

        if await self.user_repo.get_by_username(username):
            raise AlreadyExistsError(f"Username already taken: {username}")

        # Determine role: first user gets admin
        role = "user"
        if auth_settings.auto_admin_first_user:
            user_count = await self.user_repo.count_all()
            if user_count == 0:
                role = "admin"

        now = datetime.now(UTC).isoformat()
        from core.db.models.user import UserORM

        user = UserORM(
            id=secrets.token_urlsafe(16),
            email=email,
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        await self.user_repo.create(user)
        await self.session.commit()

        logger.info("user_registered", user_id=user.id, email=email, role=role)
        return {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at,
        }

    async def login(self, email: str, password: str) -> dict:
        """Authenticate user and return access + refresh tokens."""
        user = await self.user_repo.get_by_email(email)
        if not user:
            raise NotFoundError("Invalid email or password")

        if not user.is_active:
            raise PermissionDeniedError("Account is deactivated")

        if not verify_password(password, user.password_hash):
            raise NotFoundError("Invalid email or password")

        # Create tokens
        access_token = create_access_token(
            data={"sub": user.id, "email": user.email, "role": user.role}
        )
        refresh_token_str, token_id = create_refresh_token(user.id)

        # Persist refresh token
        now = datetime.now(UTC).isoformat()
        from core.db.models.user import RefreshTokenORM

        refresh_orm = RefreshTokenORM(
            id=token_id,
            user_id=user.id,
            token_hash=hashlib.sha256(refresh_token_str.encode()).hexdigest(),
            created_at=now,
            is_revoked=False,
        )
        await self.token_repo.create(refresh_orm)
        await self.session.commit()

        logger.info("user_logged_in", user_id=user.id, email=email)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token_str,
            "token_type": "bearer",
        }

    async def refresh_token(self, refresh_token_str: str) -> dict:
        """Exchange a valid refresh token for a new access token."""
        import jwt

        from core.db.models.user import RefreshTokenORM

        try:
            payload = decode_token(refresh_token_str)
        except jwt.ExpiredSignatureError:
            raise PermissionDeniedError("Refresh token expired") from None
        except jwt.InvalidTokenError:
            raise PermissionDeniedError("Invalid refresh token") from None

        if payload.get("type") != "refresh":
            raise PermissionDeniedError("Invalid token type")

        token_id = payload.get("token_id")
        user_id = payload.get("sub")
        if not token_id or not user_id:
            raise PermissionDeniedError("Invalid refresh token payload")

        # Verify token exists and not revoked
        token_orm = await self.token_repo.get_by_id(token_id)
        if not token_orm or token_orm.is_revoked:
            raise PermissionDeniedError("Refresh token revoked or not found")

        # Verify user still active
        user = await self.user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            raise PermissionDeniedError("User not found or inactive")

        # Issue new access token
        access_token = create_access_token(
            data={"sub": user.id, "email": user.email, "role": user.role}
        )
        new_refresh_token_str, new_token_id = create_refresh_token(user.id)

        token_orm.is_revoked = True

        now = datetime.now(UTC).isoformat()
        refresh_orm = RefreshTokenORM(
            id=new_token_id,
            user_id=user.id,
            token_hash=hashlib.sha256(new_refresh_token_str.encode()).hexdigest(),
            created_at=now,
            is_revoked=False,
        )
        await self.token_repo.create(refresh_orm)
        await self.session.commit()

        logger.info("token_refreshed", user_id=user.id)
        return {
            "access_token": access_token,
            "refresh_token": new_refresh_token_str,
            "token_type": "bearer",
        }

    async def revoke_refresh_token(self, token_id: str) -> None:
        """Revoke a specific refresh token by its ID."""
        token_orm = await self.token_repo.get_by_id(token_id)
        if not token_orm:
            raise NotFoundError(f"Refresh token not found: {token_id}")
        token_orm.is_revoked = True
        await self.session.commit()
        logger.info("refresh_token_revoked", token_id=token_id)

    async def create_api_key(self, user_id: str, name: str = "") -> dict:
        """Generate a new API key for the user. Returns the key only once."""
        raw_key = f"oa-{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:12]
        now = datetime.now(UTC).isoformat()

        from core.db.models.user import APIKeyORM

        api_key_orm = APIKeyORM(
            id=secrets.token_urlsafe(16),
            user_id=user_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name,
            is_active=True,
            created_at=now,
            last_used_at=None,
        )
        await self.api_key_repo.create(api_key_orm)
        await self.session.commit()

        logger.info("api_key_created", user_id=user_id, key_prefix=key_prefix)
        return {
            "id": api_key_orm.id,
            "key": raw_key,
            "key_prefix": key_prefix,
            "name": name,
            "is_active": True,
            "last_used_at": None,
            "created_at": now,
        }

    async def list_api_keys(self, user_id: str) -> list[dict]:
        """List all API keys for a user (without the actual key)."""
        keys = await self.api_key_repo.get_by_user_id(user_id)
        return [
            {
                "id": k.id,
                "key_prefix": k.key_prefix,
                "name": k.name,
                "is_active": k.is_active,
                "last_used_at": k.last_used_at,
                "created_at": k.created_at,
            }
            for k in keys
        ]

    async def revoke_api_key(self, key_id: str, user_id: str) -> None:
        """Revoke an API key. Only the owning user can revoke."""
        api_key_orm = await self.api_key_repo.get_by_id(key_id)
        if not api_key_orm:
            raise NotFoundError(f"API key not found: {key_id}")
        if api_key_orm.user_id != user_id:
            raise PermissionDeniedError("Cannot revoke another user's API key")
        api_key_orm.is_active = False
        await self.session.commit()
        logger.info("api_key_revoked", key_id=key_id, user_id=user_id)

"""Auth service unit tests — register, login, token refresh, API keys."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.db.base import Base


@pytest.fixture()
async def auth_service_session():
    """In-memory SQLite session for auth service tests."""
    from core.db.models import register_all_models
    register_all_models()

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture()
async def auth_service(auth_service_session):
    """AuthService with in-memory DB session."""
    from core.auth.service import AuthService
    return AuthService(auth_service_session)


class TestRegister:
    """AuthService.register()"""

    async def test_register_first_user_is_admin(self, auth_service):
        """First registered user gets admin role."""
        result = await auth_service.register("admin@test.com", "admin", "password123")
        assert result["role"] == "admin"
        assert result["email"] == "admin@test.com"
        assert result["is_active"] is True

    async def test_register_second_user_is_user(self, auth_service):
        """Second registered user gets user role."""
        await auth_service.register("first@test.com", "first", "password123")
        result = await auth_service.register("second@test.com", "second", "password123")
        assert result["role"] == "user"

    async def test_register_duplicate_email(self, auth_service):
        """Duplicate email raises AlreadyExistsError."""
        from core.exceptions import AlreadyExistsError
        await auth_service.register("dup@test.com", "user1", "password123")
        with pytest.raises(AlreadyExistsError):
            await auth_service.register("dup@test.com", "user2", "password123")

    async def test_register_duplicate_username(self, auth_service):
        """Duplicate username raises AlreadyExistsError."""
        from core.exceptions import AlreadyExistsError
        await auth_service.register("a@test.com", "taken", "password123")
        with pytest.raises(AlreadyExistsError):
            await auth_service.register("b@test.com", "taken", "password123")


class TestLogin:
    """AuthService.login()"""

    async def test_login_success(self, auth_service):
        """Valid credentials return tokens."""
        await auth_service.register("login@test.com", "loginuser", "password123")
        result = await auth_service.login("login@test.com", "password123")
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["token_type"] == "bearer"

    async def test_login_wrong_password(self, auth_service):
        """Wrong password raises NotFoundError."""
        from core.exceptions import NotFoundError
        await auth_service.register("wp@test.com", "wpuser", "password123")
        with pytest.raises(NotFoundError):
            await auth_service.login("wp@test.com", "wrong_password")

    async def test_login_nonexistent_email(self, auth_service):
        """Non-existent email raises NotFoundError."""
        from core.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            await auth_service.login("nobody@test.com", "password123")

    async def test_login_deactivated_user(self, auth_service):
        """Deactivated user raises PermissionDeniedError."""
        from core.exceptions import PermissionDeniedError
        result = await auth_service.register("deact@test.com", "deactuser", "password123")
        # Manually deactivate via repo
        user = await auth_service.user_repo.get_by_email("deact@test.com")
        user.is_active = False
        await auth_service.session.commit()
        with pytest.raises(PermissionDeniedError):
            await auth_service.login("deact@test.com", "password123")


class TestRefreshToken:
    """AuthService.refresh_token()"""

    async def test_refresh_token_success(self, auth_service):
        """Valid refresh token returns new access token."""
        await auth_service.register("ref@test.com", "refuser", "password123")
        login_result = await auth_service.login("ref@test.com", "password123")
        refresh_result = await auth_service.refresh_token(login_result["refresh_token"])
        assert "access_token" in refresh_result
        assert refresh_result["token_type"] == "bearer"

    async def test_refresh_with_invalid_token(self, auth_service):
        """Invalid refresh token raises PermissionDeniedError."""
        from core.exceptions import PermissionDeniedError
        with pytest.raises(PermissionDeniedError):
            await auth_service.refresh_token("invalid-token-string")


class TestAPIKey:
    """AuthService API key management."""

    async def test_create_api_key(self, auth_service):
        """Creates API key with oa- prefix."""
        result = await auth_service.register("ak@test.com", "akuser", "password123")
        key_result = await auth_service.create_api_key(result["id"], "test-key")
        assert key_result["key"].startswith("oa-")
        assert key_result["name"] == "test-key"
        assert key_result["is_active"] is True

    async def test_list_api_keys(self, auth_service):
        """Lists API keys without exposing raw key."""
        result = await auth_service.register("lk@test.com", "lkuser", "password123")
        await auth_service.create_api_key(result["id"], "key1")
        keys = await auth_service.list_api_keys(result["id"])
        assert len(keys) == 1
        assert keys[0]["name"] == "key1"
        assert "key" not in keys[0]

    async def test_revoke_api_key(self, auth_service):
        """Revoking an API key deactivates it."""
        result = await auth_service.register("rk@test.com", "rkuser", "password123")
        key_result = await auth_service.create_api_key(result["id"], "to-revoke")
        await auth_service.revoke_api_key(key_result["id"], result["id"])
        keys = await auth_service.list_api_keys(result["id"])
        assert keys[0]["is_active"] is False

    async def test_revoke_api_key_wrong_user(self, auth_service):
        """Cannot revoke another user's API key."""
        from core.exceptions import PermissionDeniedError
        user1 = await auth_service.register("u1@test.com", "user1", "password123")
        await auth_service.register("u2@test.com", "user2", "password123")
        key_result = await auth_service.create_api_key(user1["id"], "u1-key")
        with pytest.raises(PermissionDeniedError):
            await auth_service.revoke_api_key(key_result["id"], "different-user-id")

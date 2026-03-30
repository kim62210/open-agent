"""Auth dependencies unit tests — get_current_user, _validate_jwt, _validate_api_key, RoleChecker."""

import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db.base import Base


@pytest.fixture()
async def deps_engine():
    """In-memory SQLite engine for dependency tests."""
    from core.db.models import register_all_models

    register_all_models()
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def deps_factory(deps_engine):
    """Session factory bound to in-memory engine."""
    return async_sessionmaker(deps_engine, expire_on_commit=False)


@pytest.fixture()
async def seed_user(deps_factory):
    """Create a test user in the in-memory DB and return its data."""
    from core.auth.password import hash_password
    from core.db.models.user import UserORM

    async with deps_factory() as session:
        user = UserORM(
            id="dep-user-1",
            email="dep@test.com",
            username="depuser",
            password_hash=hash_password("testpass"),
            role="admin",
            is_active=True,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        session.add(user)
        await session.commit()
    return {"id": "dep-user-1", "email": "dep@test.com", "username": "depuser", "role": "admin"}


@pytest.fixture()
async def seed_inactive_user(deps_factory):
    """Create an inactive user in the in-memory DB."""
    from core.auth.password import hash_password
    from core.db.models.user import UserORM

    async with deps_factory() as session:
        user = UserORM(
            id="inactive-user-1",
            email="inactive@test.com",
            username="inactiveuser",
            password_hash=hash_password("testpass"),
            role="user",
            is_active=False,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        session.add(user)
        await session.commit()
    return {"id": "inactive-user-1"}


@pytest.fixture()
async def seed_api_key(deps_factory, seed_user):
    """Create an API key in the DB and return the raw key string."""
    from core.db.models.user import APIKeyORM

    raw_key = "oa-test-api-key-123456"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    async with deps_factory() as session:
        api_key = APIKeyORM(
            id="ak-1",
            user_id=seed_user["id"],
            key_hash=key_hash,
            key_prefix=raw_key[:12],
            name="test-key",
            is_active=True,
            created_at=datetime.now(timezone.utc).isoformat(),
            last_used_at=None,
        )
        session.add(api_key)
        await session.commit()
    return raw_key


class TestGetCurrentUser:
    """get_current_user dependency."""

    async def test_no_credentials_raises_401(self):
        """No token or API key raises 401."""
        from core.auth.dependencies import get_current_user

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=None, api_key=None)
        assert exc_info.value.status_code == 401

    async def test_jwt_takes_precedence_over_api_key(self):
        """When both JWT and API key are provided, JWT is used."""
        from core.auth.dependencies import get_current_user

        jwt_user = {"id": "jwt-user", "email": "jwt@test.com", "username": "jwt", "role": "admin"}
        with patch(
            "core.auth.dependencies._validate_jwt", new_callable=AsyncMock, return_value=jwt_user
        ):
            result = await get_current_user(token="jwt-token", api_key="oa-key")
        assert result["id"] == "jwt-user"

    async def test_api_key_used_when_no_jwt(self):
        """When no JWT but API key is present, API key path is used."""
        from core.auth.dependencies import get_current_user

        api_user = {"id": "api-user", "email": "api@test.com", "username": "apiuser", "role": "user"}
        with patch(
            "core.auth.dependencies._validate_api_key",
            new_callable=AsyncMock,
            return_value=api_user,
        ):
            result = await get_current_user(token=None, api_key="oa-key")
        assert result["id"] == "api-user"


class TestValidateJWT:
    """_validate_jwt function — exercises real decode + DB lookup."""

    async def test_valid_access_token_returns_user(self, deps_factory, seed_user):
        """Valid JWT access token returns user dict from DB."""
        from core.auth.dependencies import _validate_jwt
        from core.auth.jwt import create_access_token

        token = create_access_token(
            data={"sub": seed_user["id"], "email": seed_user["email"], "role": seed_user["role"]}
        )
        with patch("core.auth.dependencies.async_session_factory", deps_factory):
            result = await _validate_jwt(token)
        assert result["id"] == seed_user["id"]
        assert result["email"] == seed_user["email"]
        assert result["role"] == seed_user["role"]

    async def test_expired_token_raises_401(self):
        """Expired JWT raises 401."""
        import jwt as pyjwt

        from core.auth.dependencies import _validate_jwt

        with patch("core.auth.dependencies.async_session_factory") as mock_factory:
            # decode_token is called before session, so it will fail first
            expired_token = "expired.token.here"
            with patch(
                "core.auth.jwt.decode_token", side_effect=pyjwt.ExpiredSignatureError
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await _validate_jwt(expired_token)
                assert exc_info.value.status_code == 401
                assert "expired" in exc_info.value.detail.lower()

    async def test_invalid_token_raises_401(self):
        """Invalid JWT raises 401."""
        import jwt as pyjwt

        from core.auth.dependencies import _validate_jwt

        with patch("core.auth.jwt.decode_token", side_effect=pyjwt.InvalidTokenError):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_jwt("bad-token")
            assert exc_info.value.status_code == 401

    async def test_wrong_token_type_raises_401(self, deps_factory):
        """Token with type=refresh raises 401."""
        from core.auth.dependencies import _validate_jwt
        from core.auth.jwt import create_refresh_token

        refresh_token, _ = create_refresh_token("dep-user-1")
        with patch("core.auth.dependencies.async_session_factory", deps_factory):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_jwt(refresh_token)
            assert exc_info.value.status_code == 401
            assert "token type" in exc_info.value.detail.lower()

    async def test_missing_sub_raises_401(self):
        """Token without sub claim raises 401."""
        from core.auth.dependencies import _validate_jwt

        with patch(
            "core.auth.jwt.decode_token", return_value={"type": "access"}
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_jwt("no-sub-token")
            assert exc_info.value.status_code == 401

    async def test_nonexistent_user_raises_401(self, deps_factory):
        """Token with sub pointing to nonexistent user raises 401."""
        from core.auth.dependencies import _validate_jwt
        from core.auth.jwt import create_access_token

        token = create_access_token(data={"sub": "nonexistent-id", "role": "admin"})
        with patch("core.auth.dependencies.async_session_factory", deps_factory):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_jwt(token)
            assert exc_info.value.status_code == 401
            assert "not found" in exc_info.value.detail.lower()

    async def test_inactive_user_raises_401(self, deps_factory, seed_inactive_user):
        """Token for inactive user raises 401."""
        from core.auth.dependencies import _validate_jwt
        from core.auth.jwt import create_access_token

        token = create_access_token(data={"sub": seed_inactive_user["id"], "role": "user"})
        with patch("core.auth.dependencies.async_session_factory", deps_factory):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_jwt(token)
            assert exc_info.value.status_code == 401


class TestValidateAPIKey:
    """_validate_api_key function — exercises real DB lookup."""

    async def test_valid_api_key_returns_user(self, deps_factory, seed_user, seed_api_key):
        """Valid API key returns user dict from DB."""
        from core.auth.dependencies import _validate_api_key

        with patch("core.auth.dependencies.async_session_factory", deps_factory):
            result = await _validate_api_key(seed_api_key)
        assert result["id"] == seed_user["id"]
        assert result["email"] == seed_user["email"]

    async def test_invalid_api_key_raises_401(self, deps_factory, seed_user):
        """Non-existent API key raises 401."""
        from core.auth.dependencies import _validate_api_key

        with patch("core.auth.dependencies.async_session_factory", deps_factory):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_api_key("oa-nonexistent-key")
            assert exc_info.value.status_code == 401

    async def test_inactive_api_key_raises_401(self, deps_factory, seed_user):
        """Deactivated API key raises 401."""
        from core.db.models.user import APIKeyORM
        from core.auth.dependencies import _validate_api_key

        raw_key = "oa-inactive-key-999"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        async with deps_factory() as session:
            api_key = APIKeyORM(
                id="ak-inactive",
                user_id=seed_user["id"],
                key_hash=key_hash,
                key_prefix=raw_key[:12],
                name="inactive-key",
                is_active=False,
                created_at=datetime.now(timezone.utc).isoformat(),
                last_used_at=None,
            )
            session.add(api_key)
            await session.commit()

        with patch("core.auth.dependencies.async_session_factory", deps_factory):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_api_key(raw_key)
            assert exc_info.value.status_code == 401

    async def test_api_key_for_inactive_user_raises_401(self, deps_factory, seed_inactive_user):
        """API key belonging to inactive user raises 401."""
        from core.db.models.user import APIKeyORM
        from core.auth.dependencies import _validate_api_key

        raw_key = "oa-inactive-user-key"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        async with deps_factory() as session:
            api_key = APIKeyORM(
                id="ak-inactive-user",
                user_id=seed_inactive_user["id"],
                key_hash=key_hash,
                key_prefix=raw_key[:12],
                name="key-for-inactive",
                is_active=True,
                created_at=datetime.now(timezone.utc).isoformat(),
                last_used_at=None,
            )
            session.add(api_key)
            await session.commit()

        with patch("core.auth.dependencies.async_session_factory", deps_factory):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_api_key(raw_key)
            assert exc_info.value.status_code == 401


class TestRoleChecker:
    """RoleChecker dependency."""

    async def test_admin_allowed_for_admin(self):
        """Admin user passes admin role check."""
        from core.auth.dependencies import RoleChecker

        checker = RoleChecker(["admin"])
        result = await checker(current_user={"id": "u1", "role": "admin"})
        assert result["role"] == "admin"

    async def test_user_forbidden_for_admin_only(self):
        """Regular user fails admin-only check."""
        from core.auth.dependencies import RoleChecker

        checker = RoleChecker(["admin"])
        with pytest.raises(HTTPException) as exc_info:
            await checker(current_user={"id": "u2", "role": "user"})
        assert exc_info.value.status_code == 403

    async def test_viewer_forbidden_for_user_check(self):
        """Viewer fails user-level check."""
        from core.auth.dependencies import RoleChecker

        checker = RoleChecker(["admin", "user"])
        with pytest.raises(HTTPException) as exc_info:
            await checker(current_user={"id": "u3", "role": "viewer"})
        assert exc_info.value.status_code == 403

    async def test_any_role_passes_require_any(self):
        """Any role passes the require_any check."""
        from core.auth.dependencies import require_any

        for role in ["admin", "user", "viewer"]:
            result = await require_any(current_user={"id": "u", "role": role})
            assert result["role"] == role


class TestPrebuiltCheckers:
    """Verify require_admin, require_user, require_any module-level instances."""

    async def test_require_admin_rejects_user(self):
        from core.auth.dependencies import require_admin

        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user={"id": "u", "role": "user"})
        assert exc_info.value.status_code == 403

    async def test_require_user_allows_admin(self):
        from core.auth.dependencies import require_user

        result = await require_user(current_user={"id": "u", "role": "admin"})
        assert result["role"] == "admin"

    async def test_require_user_allows_user(self):
        from core.auth.dependencies import require_user

        result = await require_user(current_user={"id": "u", "role": "user"})
        assert result["role"] == "user"

    async def test_require_user_rejects_viewer(self):
        from core.auth.dependencies import require_user

        with pytest.raises(HTTPException) as exc_info:
            await require_user(current_user={"id": "u", "role": "viewer"})
        assert exc_info.value.status_code == 403

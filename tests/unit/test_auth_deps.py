"""Auth dependencies unit tests — get_current_user, RoleChecker, API key auth."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


class TestGetCurrentUser:
    """get_current_user dependency."""

    async def test_no_credentials_raises_401(self):
        """No token or API key raises 401."""
        from core.auth.dependencies import get_current_user
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=None, api_key=None)
        assert exc_info.value.status_code == 401

    async def test_valid_jwt_returns_user(self):
        """Valid JWT token returns user dict."""
        from core.auth.dependencies import get_current_user
        fake_user = {"id": "u1", "email": "a@b.com", "username": "test", "role": "admin"}
        with patch("core.auth.dependencies._validate_jwt", new_callable=AsyncMock, return_value=fake_user):
            result = await get_current_user(token="valid-token", api_key=None)
        assert result["id"] == "u1"

    async def test_valid_api_key_returns_user(self):
        """Valid API key returns user dict."""
        from core.auth.dependencies import get_current_user
        fake_user = {"id": "u2", "email": "b@c.com", "username": "test2", "role": "user"}
        with patch("core.auth.dependencies._validate_api_key", new_callable=AsyncMock, return_value=fake_user):
            result = await get_current_user(token=None, api_key="oa-valid-key")
        assert result["id"] == "u2"

    async def test_jwt_takes_precedence_over_api_key(self):
        """When both JWT and API key are provided, JWT is used."""
        from core.auth.dependencies import get_current_user
        jwt_user = {"id": "jwt-user", "email": "jwt@test.com", "username": "jwt", "role": "admin"}
        with patch("core.auth.dependencies._validate_jwt", new_callable=AsyncMock, return_value=jwt_user):
            result = await get_current_user(token="jwt-token", api_key="oa-key")
        assert result["id"] == "jwt-user"


class TestValidateJWT:
    """_validate_jwt function."""

    async def test_expired_token_raises_401(self):
        """Expired JWT raises 401."""
        import jwt as pyjwt
        from core.auth.dependencies import _validate_jwt
        with patch("core.auth.jwt.decode_token", side_effect=pyjwt.ExpiredSignatureError):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_jwt("expired-token")
            assert exc_info.value.status_code == 401

    async def test_invalid_token_raises_401(self):
        """Invalid JWT raises 401."""
        import jwt as pyjwt
        from core.auth.dependencies import _validate_jwt
        with patch("core.auth.jwt.decode_token", side_effect=pyjwt.InvalidTokenError):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_jwt("bad-token")
            assert exc_info.value.status_code == 401

    async def test_wrong_token_type_raises_401(self):
        """Token with wrong type (refresh instead of access) raises 401."""
        from core.auth.dependencies import _validate_jwt
        with patch("core.auth.jwt.decode_token", return_value={"type": "refresh", "sub": "u1"}):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_jwt("refresh-token")
            assert exc_info.value.status_code == 401

    async def test_missing_sub_raises_401(self):
        """Token without sub claim raises 401."""
        from core.auth.dependencies import _validate_jwt
        with patch("core.auth.jwt.decode_token", return_value={"type": "access"}):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_jwt("no-sub-token")
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

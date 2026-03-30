"""Auth config and rate_limit unit tests."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestAuthSettings:
    """AuthSettings (core.auth.config)."""

    def test_defaults(self):
        """Default values are sensible."""
        from core.auth.config import AuthSettings

        settings = AuthSettings()
        assert settings.jwt_algorithm == "HS256"
        assert settings.access_token_expire_minutes == 30
        assert settings.refresh_token_expire_days == 7
        assert settings.auto_admin_first_user is True
        assert settings.registration_enabled is True

    def test_get_secret_key_generates_file(self):
        """get_secret_key creates .jwt_secret file when not set."""
        from core.auth.config import AuthSettings

        settings = AuthSettings(jwt_secret_key="")
        with tempfile.TemporaryDirectory() as tmpdir:
            secret_path = Path(tmpdir) / ".jwt_secret"
            with patch("open_agent.config.get_data_dir", return_value=Path(tmpdir)):
                key = settings.get_secret_key()
            assert len(key) > 0
            assert secret_path.exists()
            # Second call reads from file
            with patch("open_agent.config.get_data_dir", return_value=Path(tmpdir)):
                key2 = settings.get_secret_key()
            assert key == key2

    def test_get_secret_key_uses_configured(self):
        """Explicit jwt_secret_key is returned directly."""
        from core.auth.config import AuthSettings

        settings = AuthSettings(jwt_secret_key="my-explicit-key")
        assert settings.get_secret_key() == "my-explicit-key"

    def test_module_level_singleton(self):
        """auth_settings is importable at module level."""
        from core.auth.config import auth_settings

        assert auth_settings is not None
        assert hasattr(auth_settings, "jwt_algorithm")


class TestRateLimit:
    """Rate limiter setup (core.auth.rate_limit)."""

    def test_limiter_exists(self):
        """limiter is a Limiter instance."""
        from slowapi import Limiter

        from core.auth.rate_limit import limiter

        assert isinstance(limiter, Limiter)

    def test_rate_limit_key_with_user(self):
        """Key function returns user ID when user is on request.state."""
        from unittest.mock import MagicMock

        from core.auth.rate_limit import _get_rate_limit_key

        request = MagicMock()
        request.state.user = {"id": "user-123"}
        assert _get_rate_limit_key(request) == "user:user-123"

    def test_rate_limit_key_without_user(self):
        """Key function falls back to remote address when no user."""
        from unittest.mock import MagicMock

        from core.auth.rate_limit import _get_rate_limit_key

        request = MagicMock()
        request.state = MagicMock(spec=[])  # no user attribute
        request.client = MagicMock()
        request.client.host = "192.168.1.100"
        # _get_rate_limit_key calls get_remote_address when no user
        result = _get_rate_limit_key(request)
        # Should not be a user: prefixed key
        assert not result.startswith("user:")


class TestAuthInit:
    """Auth __init__.py re-exports."""

    def test_all_exports(self):
        """__init__ re-exports all expected names."""
        from core.auth import (
            auth_settings,
            create_access_token,
            create_refresh_token,
            decode_token,
            get_current_user,
            hash_password,
            limiter,
            require_admin,
            require_any,
            require_user,
            verify_password,
        )

        assert auth_settings is not None
        assert callable(create_access_token)
        assert callable(create_refresh_token)
        assert callable(decode_token)
        assert callable(hash_password)
        assert callable(verify_password)
        assert limiter is not None
        assert get_current_user is not None
        assert require_admin is not None
        assert require_user is not None
        assert require_any is not None

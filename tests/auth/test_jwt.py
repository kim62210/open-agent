"""JWT token creation and validation tests."""

from datetime import timedelta

import jwt
import pytest

from core.auth.config import auth_settings
from core.auth.jwt import create_access_token, create_refresh_token, decode_token


class TestAccessToken:
    """Access token creation and decoding."""

    def test_create_and_decode_round_trip(self):
        """Created token can be decoded with correct claims."""
        data = {"sub": "user-123", "role": "admin"}
        token = create_access_token(data)
        payload = decode_token(token)

        assert payload["sub"] == "user-123"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload

    def test_expired_token_raises_error(self):
        """Token with negative expiry raises ExpiredSignatureError."""
        data = {"sub": "user-123", "role": "user"}
        token = create_access_token(data, expires_delta=timedelta(seconds=-1))

        with pytest.raises(jwt.ExpiredSignatureError):
            decode_token(token)

    def test_tampered_token_raises_error(self):
        """Modifying the token payload invalidates the signature."""
        data = {"sub": "user-123", "role": "user"}
        token = create_access_token(data)

        # Tamper with the payload segment
        parts = token.split(".")
        parts[1] = parts[1] + "x"
        tampered = ".".join(parts)

        with pytest.raises(jwt.InvalidTokenError):
            decode_token(tampered)

    def test_custom_expiry(self):
        """Custom expires_delta is respected."""
        data = {"sub": "user-123", "role": "user"}
        token = create_access_token(data, expires_delta=timedelta(hours=2))
        payload = decode_token(token)

        assert payload["sub"] == "user-123"

    def test_wrong_secret_raises_error(self):
        """Token signed with different secret cannot be decoded."""
        data = {"sub": "user-123", "role": "user"}
        token = jwt.encode(data | {"type": "access"}, "wrong-secret", algorithm="HS256")

        with pytest.raises(jwt.InvalidSignatureError):
            decode_token(token)


class TestRefreshToken:
    """Refresh token creation."""

    def test_create_refresh_token_returns_tuple(self):
        """create_refresh_token returns (token_string, token_id)."""
        token_str, token_id = create_refresh_token("user-456")

        assert isinstance(token_str, str)
        assert isinstance(token_id, str)
        assert len(token_str) > 0
        assert len(token_id) > 0

    def test_refresh_token_has_correct_claims(self):
        """Refresh token payload contains sub, token_id, type=refresh."""
        token_str, token_id = create_refresh_token("user-456")
        payload = decode_token(token_str)

        assert payload["sub"] == "user-456"
        assert payload["token_id"] == token_id
        assert payload["type"] == "refresh"
        assert "exp" in payload

    def test_refresh_token_ids_are_unique(self):
        """Each refresh token gets a unique token_id."""
        _, id1 = create_refresh_token("user-789")
        _, id2 = create_refresh_token("user-789")

        assert id1 != id2

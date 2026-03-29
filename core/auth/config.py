"""Authentication configuration."""

import secrets

from pydantic_settings import BaseSettings


class AuthSettings(BaseSettings):
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Rate limiting
    login_rate_limit: str = "5/minute"
    chat_rate_limit: str = "20/minute"
    default_rate_limit: str = "60/minute"

    # First user becomes admin
    auto_admin_first_user: bool = True

    # Allow registration (can be disabled after setup)
    registration_enabled: bool = True

    model_config = {"env_prefix": "OPEN_AGENT_"}

    def get_secret_key(self) -> str:
        """Return secret key, generating one if not set."""
        if self.jwt_secret_key:
            return self.jwt_secret_key
        from open_agent.config import get_data_dir

        secret_file = get_data_dir() / ".jwt_secret"
        if secret_file.exists():
            return secret_file.read_text().strip()
        key = secrets.token_urlsafe(64)
        secret_file.write_text(key)
        return key


auth_settings = AuthSettings()

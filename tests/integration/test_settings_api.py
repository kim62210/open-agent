"""Settings API integration tests — GET/PATCH settings, health, model validation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.fixture()
async def settings_client(_patch_db_factory, monkeypatch):
    """httpx.AsyncClient wired to settings router with mocked settings_manager."""
    import httpx
    from httpx import ASGITransport

    from fastapi import FastAPI
    from core.auth.dependencies import get_current_user
    from open_agent.api.endpoints import settings as settings_router
    from open_agent.core.settings_manager import settings_manager as _stm
    from open_agent.models.settings import AppSettings, LLMSettings, ProfileSettings, ThemeSettings

    _DEFAULT = {
        "llm": {
            "model": "gemini/gemini-2.0-flash",
            "temperature": 0.7,
            "max_tokens": 16384,
            "system_prompt": "",
        },
        "memory": {
            "enabled": True,
            "max_memories": 50,
            "max_injection_tokens": 2000,
            "compression_threshold": 0.8,
            "extraction_interval": 3,
        },
        "profile": {
            "name": "",
            "avatar": "",
            "platform_name": "Open Agent",
            "platform_subtitle": "Open Agent System",
            "bot_name": "Open Agent Core",
            "bot_avatar": "",
        },
        "theme": {
            "accent_color": "amber",
            "mode": "dark",
            "tone": "default",
            "show_blobs": True,
            "chat_bg_image": "",
            "chat_bg_opacity": 0.3,
            "chat_bg_scale": 1.1,
            "chat_bg_position_x": 50,
            "chat_bg_position_y": 50,
            "font_scale": 1.0,
        },
    }

    _stm._settings = AppSettings(**_DEFAULT)

    test_app = FastAPI()
    test_app.include_router(settings_router.router, prefix="/api/settings")

    async def _fake_current_user() -> dict:
        return {
            "id": "test-user-id",
            "email": "test@example.com",
            "username": "testuser",
            "role": "admin",
        }

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestGetLLMSettings:
    """GET /api/settings/llm"""

    async def test_get_llm_settings(self, settings_client: AsyncClient):
        """Returns current LLM settings."""
        resp = await settings_client.get("/api/settings/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert "model" in data
        assert "temperature" in data

    async def test_llm_api_key_masked(self, settings_client: AsyncClient):
        """API key is masked in the response."""
        from open_agent.core.settings_manager import settings_manager as _stm

        _stm._settings.llm.api_key = "sk-12345678secret"
        resp = await settings_client.get("/api/settings/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert "***" in data.get("api_key", "")


class TestPatchLLMSettings:
    """PATCH /api/settings/llm"""

    async def test_update_temperature(self, settings_client: AsyncClient):
        """Can update temperature via PATCH."""
        from open_agent.core.settings_manager import settings_manager as _stm

        _stm.update_llm = AsyncMock(
            return_value=_stm._settings.llm.model_copy(update={"temperature": 0.9})
        )
        resp = await settings_client.patch("/api/settings/llm", json={"temperature": 0.9})
        assert resp.status_code == 200


class TestMemorySettings:
    """GET/PATCH /api/settings/memory"""

    async def test_get_memory_settings(self, settings_client: AsyncClient):
        """Returns memory settings."""
        resp = await settings_client.get("/api/settings/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "max_memories" in data

    async def test_update_memory_settings(self, settings_client: AsyncClient):
        """Can update memory settings."""
        from open_agent.core.settings_manager import settings_manager as _stm

        _stm.update_memory = AsyncMock(
            return_value=_stm._settings.memory.model_copy(update={"max_memories": 100})
        )
        resp = await settings_client.patch("/api/settings/memory", json={"max_memories": 100})
        assert resp.status_code == 200


class TestProfileSettings:
    """GET/PATCH /api/settings/profile"""

    async def test_get_profile(self, settings_client: AsyncClient):
        """Returns profile settings."""
        resp = await settings_client.get("/api/settings/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert "platform_name" in data

    async def test_update_profile(self, settings_client: AsyncClient):
        """Can update profile name."""
        from open_agent.core.settings_manager import settings_manager as _stm

        _stm.update_profile = AsyncMock(
            return_value=_stm._settings.profile.model_copy(update={"name": "TestBot"})
        )
        resp = await settings_client.patch("/api/settings/profile", json={"name": "TestBot"})
        assert resp.status_code == 200


class TestThemeSettings:
    """GET/PATCH /api/settings/theme"""

    async def test_get_theme(self, settings_client: AsyncClient):
        """Returns theme settings."""
        resp = await settings_client.get("/api/settings/theme")
        assert resp.status_code == 200
        data = resp.json()
        assert "accent_color" in data
        assert "mode" in data

    async def test_update_theme(self, settings_client: AsyncClient):
        """Can update accent color."""
        from open_agent.core.settings_manager import settings_manager as _stm

        _stm.update_theme = AsyncMock(
            return_value=_stm._settings.theme.model_copy(update={"accent_color": "blue"})
        )
        resp = await settings_client.patch("/api/settings/theme", json={"accent_color": "blue"})
        assert resp.status_code == 200


class TestHealthCheck:
    """GET /api/settings/health"""

    async def test_health_ok_without_key(self, settings_client: AsyncClient):
        """Health check returns server=ok even without API key."""
        from open_agent.core.settings_manager import settings_manager as _stm

        _stm._settings.llm.api_key = None
        _stm._settings.llm.api_base = None
        with patch("open_agent.api.endpoints.settings.LLMClient") as mock_llm:
            mock_llm._resolve_api_key = MagicMock(return_value=None)
            resp = await settings_client.get("/api/settings/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["server"] == "ok"
        assert data["llm_connected"] is False

    async def test_health_llm_connected(self, settings_client: AsyncClient):
        """Health check succeeds when LLM responds."""
        from open_agent.core.settings_manager import settings_manager as _stm

        _stm._settings.llm.api_key = "sk-test"
        with patch(
            "open_agent.api.endpoints.settings.acompletion", new_callable=AsyncMock
        ) as mock_ac:
            with patch("open_agent.api.endpoints.settings.LLMClient") as mock_llm:
                mock_llm._resolve_api_key = MagicMock(return_value="sk-test")
                resp = await settings_client.get("/api/settings/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["server"] == "ok"
        assert data["llm_connected"] is True


class TestValidateModel:
    """POST /api/settings/validate-model"""

    async def test_validate_model_success(self, settings_client: AsyncClient):
        """Valid model returns valid=True."""
        with patch("open_agent.api.endpoints.settings.acompletion", new_callable=AsyncMock):
            with patch("open_agent.api.endpoints.settings.LLMClient") as mock_llm:
                mock_llm._resolve_api_key = MagicMock(return_value="sk-test")
                resp = await settings_client.post(
                    "/api/settings/validate-model",
                    json={"model": "gpt-4", "api_key": "sk-test"},
                )
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    async def test_validate_model_failure(self, settings_client: AsyncClient):
        """Invalid model returns valid=False."""
        with patch(
            "open_agent.api.endpoints.settings.acompletion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("bad model"),
        ):
            with patch("open_agent.api.endpoints.settings.LLMClient") as mock_llm:
                mock_llm._resolve_api_key = MagicMock(return_value=None)
                resp = await settings_client.post(
                    "/api/settings/validate-model",
                    json={"model": "bad-model"},
                )
        assert resp.status_code == 200
        assert resp.json()["valid"] is False
        assert "error" in resp.json()


class TestCustomModels:
    """Custom model CRUD endpoints."""

    async def test_get_custom_models(self, settings_client: AsyncClient):
        """GET returns empty list by default."""
        resp = await settings_client.get("/api/settings/custom-models")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_add_custom_model(self, settings_client: AsyncClient):
        """POST adds a custom model."""
        from open_agent.core.settings_manager import settings_manager as _stm
        from open_agent.models.settings import CustomModel

        result_model = CustomModel(label="My GPT", model="openai/gpt-4", provider="openai")
        _stm.add_custom_model = AsyncMock(return_value=[result_model])
        resp = await settings_client.post(
            "/api/settings/custom-models",
            json={"label": "My GPT", "model": "openai/gpt-4", "provider": "openai"},
        )
        assert resp.status_code == 200

    async def test_remove_custom_model(self, settings_client: AsyncClient):
        """DELETE removes a custom model."""
        from open_agent.core.settings_manager import settings_manager as _stm

        _stm.remove_custom_model = AsyncMock(return_value=[])
        resp = await settings_client.delete(
            "/api/settings/custom-models", params={"model": "openai/gpt-4"}
        )
        assert resp.status_code == 200


class TestHealthCheckExtended:
    """Extended health check tests."""

    async def test_health_llm_failure(self, settings_client: AsyncClient):
        """Health check reports error when LLM call fails."""
        from open_agent.core.settings_manager import settings_manager as _stm

        _stm._settings.llm.api_key = "sk-test"
        with patch(
            "open_agent.api.endpoints.settings.acompletion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Connection refused"),
        ):
            with patch("open_agent.api.endpoints.settings.LLMClient") as mock_llm:
                mock_llm._resolve_api_key = MagicMock(return_value="sk-test")
                resp = await settings_client.get("/api/settings/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["server"] == "ok"
        assert data["llm_connected"] is False
        assert "Connection refused" in data["error"]

    async def test_health_long_error_message_truncated(self, settings_client: AsyncClient):
        """Long error messages are truncated to 200 chars."""
        from open_agent.core.settings_manager import settings_manager as _stm

        _stm._settings.llm.api_key = "sk-test"
        long_error = "x" * 500
        with patch(
            "open_agent.api.endpoints.settings.acompletion",
            new_callable=AsyncMock,
            side_effect=RuntimeError(long_error),
        ):
            with patch("open_agent.api.endpoints.settings.LLMClient") as mock_llm:
                mock_llm._resolve_api_key = MagicMock(return_value="sk-test")
                resp = await settings_client.get("/api/settings/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"].endswith("...")
        assert len(data["error"]) <= 204  # 200 + "..."

    async def test_health_with_api_base_no_key(self, settings_client: AsyncClient):
        """Health check proceeds when api_base is set even without api_key."""
        from open_agent.core.settings_manager import settings_manager as _stm

        _stm._settings.llm.api_key = None
        _stm._settings.llm.api_base = "http://localhost:11434"
        with patch("open_agent.api.endpoints.settings.LLMClient") as mock_llm:
            mock_llm._resolve_api_key = MagicMock(return_value=None)
            with patch(
                "open_agent.api.endpoints.settings.acompletion", new_callable=AsyncMock
            ) as mock_ac:
                resp = await settings_client.get("/api/settings/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_connected"] is True


class TestValidateModelExtended:
    """Extended model validation tests."""

    async def test_validate_model_with_api_base(self, settings_client: AsyncClient):
        """Validate model with custom api_base."""
        with patch(
            "open_agent.api.endpoints.settings.acompletion", new_callable=AsyncMock
        ) as mock_ac:
            with patch("open_agent.api.endpoints.settings.LLMClient") as mock_llm:
                mock_llm._resolve_api_key = MagicMock(return_value=None)
                resp = await settings_client.post(
                    "/api/settings/validate-model",
                    json={"model": "local-model", "api_base": "http://localhost:11434"},
                )
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    async def test_validate_model_long_error_truncated(self, settings_client: AsyncClient):
        """Long validation error is truncated to 300 chars."""
        long_error = "e" * 600
        with patch(
            "open_agent.api.endpoints.settings.acompletion",
            new_callable=AsyncMock,
            side_effect=RuntimeError(long_error),
        ):
            with patch("open_agent.api.endpoints.settings.LLMClient") as mock_llm:
                mock_llm._resolve_api_key = MagicMock(return_value=None)
                resp = await settings_client.post(
                    "/api/settings/validate-model",
                    json={"model": "bad-model"},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data["error"].endswith("...")


class TestDiscoverModels:
    """GET /api/settings/models/discover"""

    async def test_discover_single_provider(self, settings_client: AsyncClient):
        """Discover models for a single provider."""
        with patch(
            "open_agent.api.endpoints.settings._discover_provider",
            return_value=[{"id": "openai/gpt-4", "name": "gpt-4"}],
        ) as mock_disc:
            resp = await settings_client.get(
                "/api/settings/models/discover", params={"provider": "openai"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        assert "openai" in data["providers"]

    async def test_discover_all_providers(self, settings_client: AsyncClient):
        """Discover models from all providers."""
        with patch(
            "open_agent.api.endpoints.settings._discover_provider", return_value=[]
        ) as mock_disc:
            resp = await settings_client.get("/api/settings/models/discover")
        assert resp.status_code == 200
        assert "providers" in resp.json()

    async def test_discover_empty_provider(self, settings_client: AsyncClient):
        """Returns empty list for provider with no API key."""
        with patch("open_agent.api.endpoints.settings._discover_provider", return_value=[]):
            resp = await settings_client.get(
                "/api/settings/models/discover", params={"provider": "anthropic"}
            )
        assert resp.status_code == 200


class TestVersionEndpoint:
    """GET /api/settings/version"""

    async def test_get_version(self, settings_client: AsyncClient):
        """Version endpoint returns current version info."""
        with patch(
            "open_agent.api.endpoints.settings._fetch_version_sync",
            return_value={"current": "0.8.6", "latest": "0.8.6", "update_available": False},
        ):
            resp = await settings_client.get("/api/settings/version")
        assert resp.status_code == 200
        data = resp.json()
        assert "current" in data
        assert "update_available" in data

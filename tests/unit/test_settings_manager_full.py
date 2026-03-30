"""SettingsManager unit tests — async DB-backed."""

import pytest

from open_agent.core.settings_manager import SettingsManager
from open_agent.models.settings import AppSettings, LLMSettings, ThemeSettings


class TestSettingsManagerInit:
    """Initialization and default value tests."""

    async def test_initial_state(self, settings_manager: SettingsManager):
        """Manager starts with default AppSettings."""
        assert isinstance(settings_manager.settings, AppSettings)
        assert settings_manager._initialized is False

    async def test_default_llm_settings(self, settings_manager: SettingsManager):
        """LLM property returns default LLMSettings."""
        llm = settings_manager.llm
        assert isinstance(llm, LLMSettings)
        assert llm.temperature == 0.7
        assert llm.max_tokens > 0

    async def test_default_memory_settings(self, settings_manager: SettingsManager):
        """Memory property returns default MemorySettings."""
        mem = settings_manager.memory
        assert mem.enabled is True
        assert mem.max_memories == 50

    async def test_default_profile_settings(self, settings_manager: SettingsManager):
        """Profile property returns default ProfileSettings."""
        profile = settings_manager.profile
        assert profile.platform_name == "Open Agent"

    async def test_default_theme_settings(self, settings_manager: SettingsManager):
        """Theme property returns default ThemeSettings."""
        theme = settings_manager.theme
        assert isinstance(theme, ThemeSettings)
        assert theme.mode == "dark"
        assert theme.accent_color == "amber"

    async def test_custom_models_initially_empty(self, settings_manager: SettingsManager):
        """Custom models list is empty by default."""
        assert settings_manager.custom_models == []


class TestSettingsLoadFromDB:
    """load_from_db persistence tests."""

    async def test_load_from_db_creates_defaults_when_empty(
        self, settings_manager: SettingsManager
    ):
        """First load saves defaults to DB and marks initialized."""
        await settings_manager.load_from_db()
        assert settings_manager._initialized is True

    async def test_load_from_db_round_trip(self, settings_manager: SettingsManager):
        """Settings saved via load_from_db can be reloaded."""
        await settings_manager.load_from_db()

        # Modify in-memory, then persist through update_llm
        await settings_manager.update_llm(model="gpt-4o")

        # Create a new manager and load from the same DB
        mgr2 = SettingsManager()
        await mgr2.load_from_db()
        assert mgr2.llm.model == "gpt-4o"

    async def test_load_from_db_with_invalid_data(self, settings_manager: SettingsManager):
        """Invalid data in DB falls back to defaults gracefully."""
        # First save something to DB
        await settings_manager.load_from_db()

        # Manually corrupt the DB data
        from core.db.engine import async_session_factory
        from core.db.repositories.settings_repo import SettingsRepository

        async with async_session_factory() as session:
            repo = SettingsRepository(session)
            await repo.save_settings({"llm": {"temperature": "not_a_number_but_pydantic_coerces"}})
            await session.commit()

        # Reload should fall back to defaults on parse error or coerce
        mgr2 = SettingsManager()
        await mgr2.load_from_db()
        assert mgr2._initialized is True


class TestUpdateLLM:
    """LLM settings update tests."""

    async def test_update_model(self, settings_manager: SettingsManager):
        """Model can be updated."""
        result = await settings_manager.update_llm(model="claude-3-opus")
        assert result.model == "claude-3-opus"
        assert settings_manager.llm.model == "claude-3-opus"

    async def test_update_temperature(self, settings_manager: SettingsManager):
        """Temperature can be updated."""
        result = await settings_manager.update_llm(temperature=0.3)
        assert result.temperature == 0.3

    async def test_update_multiple_fields(self, settings_manager: SettingsManager):
        """Multiple fields can be updated in one call."""
        result = await settings_manager.update_llm(
            model="gpt-4", temperature=0.5, max_tokens=4096
        )
        assert result.model == "gpt-4"
        assert result.temperature == 0.5
        assert result.max_tokens == 4096

    async def test_update_none_values_ignored(self, settings_manager: SettingsManager):
        """None values are ignored (non-nullable fields)."""
        original_model = settings_manager.llm.model
        result = await settings_manager.update_llm(model=None)
        assert result.model == original_model

    async def test_update_api_key_nullable(self, settings_manager: SettingsManager):
        """api_key is a nullable field — None is allowed."""
        await settings_manager.update_llm(api_key="sk-test")
        assert settings_manager.llm.api_key == "sk-test"

        result = await settings_manager.update_llm(api_key=None)
        assert result.api_key is None

    async def test_update_api_base_nullable(self, settings_manager: SettingsManager):
        """api_base is a nullable field — None clears it."""
        await settings_manager.update_llm(api_base="http://localhost:8000")
        assert settings_manager.llm.api_base == "http://localhost:8000"

        result = await settings_manager.update_llm(api_base=None)
        assert result.api_base is None

    async def test_update_persists_to_db(self, settings_manager: SettingsManager):
        """LLM update persists to DB."""
        await settings_manager.update_llm(model="test-persist-model")

        mgr2 = SettingsManager()
        await mgr2.load_from_db()
        assert mgr2.llm.model == "test-persist-model"


class TestUpdateMemory:
    """Memory settings update tests."""

    async def test_update_enabled(self, settings_manager: SettingsManager):
        """Memory can be disabled."""
        result = await settings_manager.update_memory(enabled=False)
        assert result.enabled is False

    async def test_update_max_memories(self, settings_manager: SettingsManager):
        """max_memories can be updated."""
        result = await settings_manager.update_memory(max_memories=100)
        assert result.max_memories == 100

    async def test_update_none_ignored(self, settings_manager: SettingsManager):
        """None values are ignored in memory update."""
        original = settings_manager.memory.max_memories
        result = await settings_manager.update_memory(max_memories=None)
        assert result.max_memories == original


class TestUpdateProfile:
    """Profile settings update tests."""

    async def test_update_name(self, settings_manager: SettingsManager):
        """Profile name can be updated."""
        result = await settings_manager.update_profile(name="Test User")
        assert result.name == "Test User"

    async def test_update_platform_name(self, settings_manager: SettingsManager):
        """Platform name can be updated."""
        result = await settings_manager.update_profile(platform_name="My Agent")
        assert result.platform_name == "My Agent"

    async def test_update_persists(self, settings_manager: SettingsManager):
        """Profile update persists to DB."""
        await settings_manager.update_profile(name="Persistent Name")

        mgr2 = SettingsManager()
        await mgr2.load_from_db()
        assert mgr2.profile.name == "Persistent Name"


class TestUpdateTheme:
    """Theme settings update tests."""

    async def test_update_accent_color(self, settings_manager: SettingsManager):
        """Accent color can be changed."""
        result = await settings_manager.update_theme(accent_color="blue")
        assert result.accent_color == "blue"

    async def test_update_mode(self, settings_manager: SettingsManager):
        """Theme mode can be changed."""
        result = await settings_manager.update_theme(mode="light")
        assert result.mode == "light"

    async def test_update_font_scale(self, settings_manager: SettingsManager):
        """Font scale can be updated."""
        result = await settings_manager.update_theme(font_scale=1.2)
        assert result.font_scale == 1.2

    async def test_update_persists(self, settings_manager: SettingsManager):
        """Theme update persists to DB."""
        await settings_manager.update_theme(accent_color="green")

        mgr2 = SettingsManager()
        await mgr2.load_from_db()
        assert mgr2.theme.accent_color == "green"


class TestCustomModels:
    """Custom model management tests."""

    async def test_add_custom_model(self, settings_manager: SettingsManager):
        """Custom model can be added."""
        result = await settings_manager.add_custom_model(
            label="GPT-4", model="openai/gpt-4", provider="openai"
        )
        assert len(result) == 1
        assert result[0].label == "GPT-4"
        assert result[0].model == "openai/gpt-4"
        assert result[0].provider == "openai"

    async def test_add_duplicate_model_ignored(self, settings_manager: SettingsManager):
        """Adding a model with the same model ID is ignored."""
        await settings_manager.add_custom_model(
            label="GPT-4", model="openai/gpt-4", provider="openai"
        )
        result = await settings_manager.add_custom_model(
            label="GPT-4 Duplicate", model="openai/gpt-4", provider="openai"
        )
        assert len(result) == 1
        assert result[0].label == "GPT-4"  # original label preserved

    async def test_add_multiple_models(self, settings_manager: SettingsManager):
        """Multiple different models can be added."""
        await settings_manager.add_custom_model("GPT-4", "openai/gpt-4", "openai")
        result = await settings_manager.add_custom_model("Claude", "anthropic/claude-3", "anthropic")
        assert len(result) == 2

    async def test_remove_custom_model(self, settings_manager: SettingsManager):
        """Custom model can be removed."""
        await settings_manager.add_custom_model("GPT-4", "openai/gpt-4", "openai")
        await settings_manager.add_custom_model("Claude", "anthropic/claude-3", "anthropic")

        result = await settings_manager.remove_custom_model("openai/gpt-4")
        assert len(result) == 1
        assert result[0].model == "anthropic/claude-3"

    async def test_remove_nonexistent_model(self, settings_manager: SettingsManager):
        """Removing a non-existent model is a no-op."""
        result = await settings_manager.remove_custom_model("nonexistent")
        assert len(result) == 0

    async def test_custom_models_persist(self, settings_manager: SettingsManager):
        """Custom models persist to DB."""
        await settings_manager.add_custom_model("GPT-4", "openai/gpt-4", "openai")

        mgr2 = SettingsManager()
        await mgr2.load_from_db()
        assert len(mgr2.custom_models) == 1
        assert mgr2.custom_models[0].model == "openai/gpt-4"

import asyncio
import logging
from typing import Optional

from open_agent.models.memory import MemorySettings
from open_agent.models.settings import AppSettings, CustomModel, LLMSettings, ProfileSettings, ThemeSettings

logger = logging.getLogger(__name__)


class SettingsManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._settings = AppSettings()
        self._initialized = False

    @property
    def llm(self) -> LLMSettings:
        return self._settings.llm

    @property
    def memory(self) -> MemorySettings:
        return self._settings.memory

    @property
    def profile(self) -> ProfileSettings:
        return self._settings.profile

    @property
    def theme(self) -> ThemeSettings:
        return self._settings.theme

    @property
    def settings(self) -> AppSettings:
        return self._settings

    async def load_from_db(self) -> None:
        """Load settings from database. Creates default row if not found."""
        async with self._lock:
            from core.db.engine import async_session_factory
            from core.db.repositories.settings_repo import SettingsRepository

            async with async_session_factory() as session:
                repo = SettingsRepository(session)
                data = await repo.get_settings()
                if data:
                    try:
                        self._settings = AppSettings(**data)
                        logger.info("Loaded settings from database")
                    except Exception as e:
                        logger.warning(f"Failed to parse settings from DB: {e}, using defaults")
                        self._settings = AppSettings()
                else:
                    logger.info("No settings in DB, saving defaults")
                    await repo.save_settings(self._settings.model_dump())
                    await session.commit()
            self._initialized = True

    async def _persist(self) -> None:
        """Write current in-memory settings to database."""
        from core.db.engine import async_session_factory
        from core.db.repositories.settings_repo import SettingsRepository

        async with async_session_factory() as session:
            repo = SettingsRepository(session)
            await repo.save_settings(self._settings.model_dump())
            await session.commit()

    async def update_llm(self, **kwargs) -> LLMSettings:
        async with self._lock:
            current = self._settings.llm.model_dump()
            _nullable_fields = {"api_key", "api_base"}
            for k, v in kwargs.items():
                if k in _nullable_fields:
                    current[k] = v
                elif v is not None:
                    current[k] = v
            self._settings.llm = LLMSettings(**current)
            await self._persist()
            logger.info(f"Updated LLM settings: model={self._settings.llm.model}")
            return self._settings.llm

    async def update_memory(self, **kwargs) -> MemorySettings:
        async with self._lock:
            current = self._settings.memory.model_dump()
            for k, v in kwargs.items():
                if v is not None:
                    current[k] = v
            self._settings.memory = MemorySettings(**current)
            await self._persist()
            logger.info(f"Updated memory settings: enabled={self._settings.memory.enabled}")
            return self._settings.memory

    async def update_profile(self, **kwargs) -> ProfileSettings:
        async with self._lock:
            current = self._settings.profile.model_dump()
            for k, v in kwargs.items():
                if v is not None:
                    current[k] = v
            self._settings.profile = ProfileSettings(**current)
            await self._persist()
            logger.info(f"Updated profile settings: name={self._settings.profile.name}")
            return self._settings.profile

    async def update_theme(self, **kwargs) -> ThemeSettings:
        async with self._lock:
            current = self._settings.theme.model_dump()
            for k, v in kwargs.items():
                if v is not None:
                    current[k] = v
            self._settings.theme = ThemeSettings(**current)
            await self._persist()
            logger.info(f"Updated theme settings: mode={self._settings.theme.mode}, accent={self._settings.theme.accent_color}")
            return self._settings.theme

    @property
    def custom_models(self) -> list[CustomModel]:
        return self._settings.custom_models

    async def add_custom_model(self, label: str, model: str, provider: str) -> list[CustomModel]:
        async with self._lock:
            if any(cm.model == model for cm in self._settings.custom_models):
                logger.warning(f"Custom model already exists: {model}")
                return self._settings.custom_models
            self._settings.custom_models.append(CustomModel(label=label, model=model, provider=provider))
            await self._persist()
            logger.info(f"Added custom model: {label} ({model})")
            return self._settings.custom_models

    async def remove_custom_model(self, model: str) -> list[CustomModel]:
        async with self._lock:
            self._settings.custom_models = [cm for cm in self._settings.custom_models if cm.model != model]
            await self._persist()
            logger.info(f"Removed custom model: {model}")
            return self._settings.custom_models


settings_manager = SettingsManager()

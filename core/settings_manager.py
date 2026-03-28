import json
import logging
from pathlib import Path
from typing import Optional

from open_agent.models.memory import MemorySettings
from open_agent.models.settings import AppSettings, CustomModel, LLMSettings, ProfileSettings, ThemeSettings

logger = logging.getLogger(__name__)


class SettingsManager:
    def __init__(self):
        self._settings = AppSettings()
        self._config_path: Optional[Path] = None

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

    def load_config(self, config_path: str) -> None:
        path = Path(config_path)
        if not path.is_absolute():
            from open_agent.config import get_config_path
            path = get_config_path(config_path)
        self._config_path = path

        if not path.exists():
            logger.info(f"Settings file not found: {path}, using defaults")
            self._save_config()
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._settings = AppSettings(**data)
            logger.info(f"Loaded settings from {path}")
            # 불완전한 설정 파일 backfill: 누락된 섹션을 디스크에 저장
            _REQUIRED_KEYS = {"llm", "memory", "profile", "theme"}
            if not _REQUIRED_KEYS.issubset(data.keys()):
                self._save_config()
                logger.info("Persisted missing default settings sections to disk")
        except Exception as e:
            logger.warning(f"Failed to parse settings: {e}, using defaults")
            self._settings = AppSettings()

    def _save_config(self) -> None:
        if not self._config_path:
            return
        data = self._settings.model_dump()
        self._config_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def update_llm(self, **kwargs) -> LLMSettings:
        current = self._settings.llm.model_dump()
        # None 허용 필드: api_key, api_base (사용자가 삭제 가능)
        _nullable_fields = {"api_key", "api_base"}
        for k, v in kwargs.items():
            if k in _nullable_fields:
                current[k] = v  # None 포함 저장
            elif v is not None:
                current[k] = v
        self._settings.llm = LLMSettings(**current)
        self._save_config()
        logger.info(f"Updated LLM settings: model={self._settings.llm.model}")
        return self._settings.llm

    def update_memory(self, **kwargs) -> MemorySettings:
        current = self._settings.memory.model_dump()
        for k, v in kwargs.items():
            if v is not None:
                current[k] = v
        self._settings.memory = MemorySettings(**current)
        self._save_config()
        logger.info(f"Updated memory settings: enabled={self._settings.memory.enabled}")
        return self._settings.memory

    def update_profile(self, **kwargs) -> ProfileSettings:
        current = self._settings.profile.model_dump()
        for k, v in kwargs.items():
            if v is not None:
                current[k] = v
        self._settings.profile = ProfileSettings(**current)
        self._save_config()
        logger.info(f"Updated profile settings: name={self._settings.profile.name}")
        return self._settings.profile

    def update_theme(self, **kwargs) -> ThemeSettings:
        current = self._settings.theme.model_dump()
        for k, v in kwargs.items():
            if v is not None:
                current[k] = v
        self._settings.theme = ThemeSettings(**current)
        self._save_config()
        logger.info(f"Updated theme settings: mode={self._settings.theme.mode}, accent={self._settings.theme.accent_color}")
        return self._settings.theme

    @property
    def custom_models(self) -> list[CustomModel]:
        return self._settings.custom_models

    def add_custom_model(self, label: str, model: str, provider: str) -> list[CustomModel]:
        if any(cm.model == model for cm in self._settings.custom_models):
            logger.warning(f"Custom model already exists: {model}")
            return self._settings.custom_models
        self._settings.custom_models.append(CustomModel(label=label, model=model, provider=provider))
        self._save_config()
        logger.info(f"Added custom model: {label} ({model})")
        return self._settings.custom_models

    def remove_custom_model(self, model: str) -> list[CustomModel]:
        self._settings.custom_models = [cm for cm in self._settings.custom_models if cm.model != model]
        self._save_config()
        logger.info(f"Removed custom model: {model}")
        return self._settings.custom_models


settings_manager = SettingsManager()

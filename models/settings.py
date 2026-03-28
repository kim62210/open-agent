from typing import Optional
from pydantic import BaseModel

from open_agent.models.memory import MemorySettings


class LLMSettings(BaseModel):
    model: str = "hosted_vllm/openai/gpt-oss-120b"
    api_base: Optional[str] = "http://192.168.1.121:11436/v1"
    api_key: Optional[str] = "dummy"  # override, 미설정 시 env GOOGLE_API_KEY 사용
    temperature: float = 0.7
    max_tokens: int = 32768
    max_tool_rounds: int = 25
    system_prompt: str = ""
    deferred_tool_loading: bool = False  # True: find_tools로 도구 동적 로드
    deferred_tool_threshold: int = 20  # 전체 도구 수가 이 값을 초과하면 자동으로 deferred 모드 활성화 (0=비활성)
    system_prompt_budget: int = 0  # 시스템 프롬프트 최대 글자수 (0=무제한)
    context_window: int = 0  # 모델 컨텍스트 윈도우 (토큰, 0=LiteLLM 자동 감지)
    compact_threshold: float = 0.7  # 컨텍스트 사용률이 이 비율 초과 시 압축 트리거
    reasoning_effort: str = "medium"  # low / medium / high — 작업 복잡도에 따라 동적 조절 가능


class ProfileSettings(BaseModel):
    name: str = ""
    avatar: str = ""  # base64 data URI
    platform_name: str = "Open Agent"
    platform_subtitle: str = "Open Agent System"
    bot_name: str = "Open Agent Core"
    bot_avatar: str = ""  # base64 data URI


class ThemeSettings(BaseModel):
    accent_color: str = "amber"
    mode: str = "dark"
    tone: str = "default"
    show_blobs: bool = True
    chat_bg_image: str = ""
    chat_bg_opacity: float = 0.3
    chat_bg_scale: float = 1.1
    chat_bg_position_x: float = 50
    chat_bg_position_y: float = 50
    font_scale: float = 1.0


class CustomModel(BaseModel):
    label: str       # 표시명
    model: str       # LiteLLM 모델 ID
    provider: str    # 프로바이더 그룹 키


class AppSettings(BaseModel):
    llm: LLMSettings = LLMSettings()
    memory: MemorySettings = MemorySettings()
    profile: ProfileSettings = ProfileSettings()
    theme: ThemeSettings = ThemeSettings()
    custom_models: list[CustomModel] = []


class UpdateLLMRequest(BaseModel):
    model: Optional[str] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_tool_rounds: Optional[int] = None
    system_prompt: Optional[str] = None
    context_window: Optional[int] = None
    compact_threshold: Optional[float] = None


class UpdateMemorySettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    max_memories: Optional[int] = None
    max_injection_tokens: Optional[int] = None
    compression_threshold: Optional[float] = None
    extraction_interval: Optional[int] = None


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    platform_name: Optional[str] = None
    platform_subtitle: Optional[str] = None
    bot_name: Optional[str] = None
    bot_avatar: Optional[str] = None


class UpdateThemeRequest(BaseModel):
    accent_color: Optional[str] = None
    mode: Optional[str] = None
    tone: Optional[str] = None
    show_blobs: Optional[bool] = None
    chat_bg_image: Optional[str] = None
    chat_bg_opacity: Optional[float] = None
    chat_bg_scale: Optional[float] = None
    chat_bg_position_x: Optional[float] = None
    chat_bg_position_y: Optional[float] = None
    font_scale: Optional[float] = None

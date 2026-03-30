from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from open_agent.models.memory import MemorySettings


class LLMSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    model: str = "hosted_vllm/openai/gpt-oss-120b"
    api_base: Optional[str] = "http://192.168.1.121:11436/v1"
    api_key: Optional[str] = "dummy"  # override, 미설정 시 env GOOGLE_API_KEY 사용
    temperature: float = 0.7
    max_tokens: int = 32768
    max_tool_rounds: int = 25
    system_prompt: str = ""
    deferred_tool_loading: bool = False  # True: find_tools로 도구 동적 로드
    deferred_tool_threshold: int = (
        20  # 전체 도구 수가 이 값을 초과하면 자동으로 deferred 모드 활성화 (0=비활성)
    )
    system_prompt_budget: int = 0  # 시스템 프롬프트 최대 글자수 (0=무제한)
    context_window: int = 0  # 모델 컨텍스트 윈도우 (토큰, 0=LiteLLM 자동 감지)
    compact_threshold: float = 0.7  # 컨텍스트 사용률이 이 비율 초과 시 압축 트리거
    reasoning_effort: Literal["low", "medium", "high"] = "medium"
    timeout: int = 120  # LLM request timeout in seconds


class ProfileSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    name: str = ""
    avatar: str = ""  # base64 data URI
    platform_name: str = "Open Agent"
    platform_subtitle: str = "Open Agent System"
    bot_name: str = "Open Agent Core"
    bot_avatar: str = ""  # base64 data URI


class ThemeSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    accent_color: str = "amber"
    mode: Literal["dark", "light", "system"] = "dark"
    tone: str = "default"
    show_blobs: bool = True
    chat_bg_image: str = ""
    chat_bg_opacity: float = 0.3
    chat_bg_scale: float = 1.1
    chat_bg_position_x: float = 50
    chat_bg_position_y: float = 50
    font_scale: float = 1.0


class ApprovalSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    risk_based_approval: bool = True
    allowed_mcp_servers: list[str] = Field(default_factory=list)
    allowed_tool_names: list[str] = Field(default_factory=list)


class CustomModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    label: str  # 표시명
    model: str  # LiteLLM 모델 ID
    provider: str  # 프로바이더 그룹 키


class AppSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    llm: LLMSettings = LLMSettings()
    memory: MemorySettings = MemorySettings()
    profile: ProfileSettings = ProfileSettings()
    theme: ThemeSettings = ThemeSettings()
    approval: ApprovalSettings = ApprovalSettings()
    custom_models: list[CustomModel] = Field(default_factory=list)


class UpdateLLMRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

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
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    enabled: Optional[bool] = None
    max_memories: Optional[int] = None
    max_injection_tokens: Optional[int] = None
    compression_threshold: Optional[float] = None
    extraction_interval: Optional[int] = None


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    name: Optional[str] = None
    avatar: Optional[str] = None
    platform_name: Optional[str] = None
    platform_subtitle: Optional[str] = None
    bot_name: Optional[str] = None
    bot_avatar: Optional[str] = None


class UpdateThemeRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    accent_color: Optional[str] = None
    mode: Optional[Literal["dark", "light", "system"]] = None
    tone: Optional[str] = None
    show_blobs: Optional[bool] = None
    chat_bg_image: Optional[str] = None
    chat_bg_opacity: Optional[float] = None
    chat_bg_scale: Optional[float] = None
    chat_bg_position_x: Optional[float] = None
    chat_bg_position_y: Optional[float] = None
    font_scale: Optional[float] = None

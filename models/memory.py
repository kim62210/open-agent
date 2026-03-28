from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


MemoryCategory = Literal["preference", "context", "pattern", "fact"]
MemorySource = Literal["user_input", "tool_output", "llm_inference"]


class MemoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    content: str
    category: MemoryCategory = "fact"
    confidence: float = 0.7  # 0.0~1.0, 기존 메모리 호환용 기본값
    source: MemorySource = "llm_inference"
    is_pinned: bool = False
    created_at: str
    updated_at: str


class CreateMemoryRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    content: str = Field(..., min_length=1, max_length=5000)
    category: MemoryCategory = "fact"
    confidence: float = Field(0.7, ge=0.0, le=1.0)


class UpdateMemoryRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    content: Optional[str] = Field(None, min_length=1, max_length=5000)
    category: Optional[MemoryCategory] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    is_pinned: Optional[bool] = None


class MemorySettings(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    enabled: bool = True
    max_memories: int = 50
    max_injection_tokens: int = 2000
    compression_threshold: float = 0.8  # 80% 도달 시 압축 트리거
    extraction_interval: int = 1  # N턴마다 배치 추출 (1=매턴, 3=3턴마다)

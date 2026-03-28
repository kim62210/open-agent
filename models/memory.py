from typing import Optional, Literal
from pydantic import BaseModel, Field


MemoryCategory = Literal["preference", "context", "pattern", "fact"]
MemorySource = Literal["user_input", "tool_output", "llm_inference"]


class MemoryItem(BaseModel):
    id: str
    content: str
    category: MemoryCategory = "fact"
    confidence: float = 0.7  # 0.0~1.0, 기존 메모리 호환용 기본값
    source: MemorySource = "llm_inference"
    is_pinned: bool = False
    created_at: str
    updated_at: str


class CreateMemoryRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    category: MemoryCategory = "fact"
    confidence: float = Field(0.7, ge=0.0, le=1.0)


class UpdateMemoryRequest(BaseModel):
    content: Optional[str] = Field(None, min_length=1, max_length=5000)
    category: Optional[MemoryCategory] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    is_pinned: Optional[bool] = None


class MemorySettings(BaseModel):
    enabled: bool = True
    max_memories: int = 50
    max_injection_tokens: int = 2000
    compression_threshold: float = 0.8  # 80% 도달 시 압축 트리거
    extraction_interval: int = 1  # N턴마다 배치 추출 (1=매턴, 3=3턴마다)

from typing import List, Optional, Union
from pydantic import BaseModel


class SessionMessage(BaseModel):
    role: str  # "user" | "assistant" | "tool"
    content: Union[str, list]  # str or multimodal array
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    timestamp: Optional[str] = None
    thinking_steps: Optional[list] = None  # 도구 호출/결과/사고 과정 보존
    display_text: Optional[str] = None  # 파일 첨부 시 UI 표시용 텍스트 (파일 내용 제외)
    attached_files: Optional[list] = None  # [{name, size, isImage}]


class SessionInfo(BaseModel):
    id: str
    title: str
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    message_count: int = 0
    preview: str = ""


class CreateSessionRequest(BaseModel):
    title: str = ""


class UpdateSessionRequest(BaseModel):
    title: str


class SaveMessagesRequest(BaseModel):
    messages: List[SessionMessage]


class SessionDetail(BaseModel):
    """세션 상세 (메타 + 메시지)"""
    info: SessionInfo
    messages: List[SessionMessage]

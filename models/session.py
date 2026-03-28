from enum import Enum
from typing import Any, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"


class SessionMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    role: MessageRole
    content: Union[str, list[dict[str, Any]]]
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    timestamp: Optional[str] = None
    thinking_steps: Optional[list[dict[str, Any]]] = None
    display_text: Optional[str] = None
    attached_files: Optional[list[dict[str, Any]]] = None


class SessionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    title: str
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    message_count: int = 0
    preview: str = ""


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    title: str = ""


class UpdateSessionRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    title: str


class SaveMessagesRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    messages: List[SessionMessage]


class SessionDetail(BaseModel):
    """세션 상세 (메타 + 메시지)"""
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    info: SessionInfo
    messages: List[SessionMessage]

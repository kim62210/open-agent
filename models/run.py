from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    event_type: str
    payload: dict[str, Any] | None = None
    created_at: str


class RunDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_user_id: str
    status: str
    request_messages: list[dict[str, Any]] = Field(default_factory=list)
    response_payload: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str
    finished_at: str | None = None
    events: list[RunEvent] = Field(default_factory=list)

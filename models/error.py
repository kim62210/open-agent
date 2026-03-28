"""표준 에러 응답 스키마."""
from typing import Optional
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    field: Optional[str] = None
    message: str
    code: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    code: str
    details: Optional[list[ErrorDetail]] = None
    request_id: Optional[str] = None

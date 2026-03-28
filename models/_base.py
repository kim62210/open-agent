"""Shared base model for Open Agent."""
from pydantic import BaseModel, ConfigDict


class OpenAgentBase(BaseModel):
    """전체 모델 공통 베이스 — 직렬화 일관성 보장."""
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )

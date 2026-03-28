from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SkillInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    name: str
    description: str
    path: str
    scripts: List[str] = Field(default_factory=list)
    references: List[str] = Field(default_factory=list)
    enabled: bool = True
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    allowed_tools: List[str] = Field(default_factory=list)
    is_bundled: bool = False
    version: str = "1.0.0"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SkillDetail(SkillInfo):
    content: str = ""


class CreateSkillRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    name: str
    description: str
    instructions: str = ""


class UpdateSkillRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    enabled: Optional[bool] = None
    description: Optional[str] = None
    instructions: Optional[str] = None

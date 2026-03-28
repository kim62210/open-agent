from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SkillInfo(BaseModel):
    name: str
    description: str
    path: str
    scripts: List[str] = []
    references: List[str] = []
    enabled: bool = True
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    allowed_tools: List[str] = []  # 스킬이 의존하는 MCP 도구명 목록
    is_bundled: bool = False
    version: str = "1.0.0"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SkillDetail(SkillInfo):
    content: str = ""


class CreateSkillRequest(BaseModel):
    name: str
    description: str
    instructions: str = ""


class UpdateSkillRequest(BaseModel):
    enabled: Optional[bool] = None
    description: Optional[str] = None
    instructions: Optional[str] = None

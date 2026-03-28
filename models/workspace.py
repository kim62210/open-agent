from typing import List, Literal, Optional

from pydantic import BaseModel


class WorkspaceInfo(BaseModel):
    id: str  # uuid.hex[:8]
    name: str
    path: str  # 절대 경로
    description: str = ""
    created_at: str  # ISO 8601
    is_active: bool = False


class FileTreeNode(BaseModel):
    name: str
    path: str  # 워크스페이스 루트 기준 상대 경로
    type: Literal["file", "dir"]
    size: int = 0
    children: Optional[List["FileTreeNode"]] = None


class FileContent(BaseModel):
    path: str
    content: str
    total_lines: int
    offset: int = 0
    limit: Optional[int] = None


# Request 모델


class CreateWorkspaceRequest(BaseModel):
    name: str
    path: str
    description: str = ""


class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class WriteFileRequest(BaseModel):
    path: str
    content: str


class EditFileRequest(BaseModel):
    path: str
    old_string: str
    new_string: str
    replace_all: bool = False

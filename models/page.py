from typing import Optional
from pydantic import BaseModel


class PageInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    content_type: str = "html"        # "html" | "url" | "folder" | "bundle"
    parent_id: Optional[str] = None   # null = root level
    filename: Optional[str] = None
    size_bytes: int = 0
    entry_file: Optional[str] = None  # bundle entry point (e.g. "index.html")
    url: Optional[str] = None
    frameable: Optional[bool] = None
    published: bool = False
    host_password_hash: Optional[str] = None  # SHA-256 hash for hosted page access


class CreatePageRequest(BaseModel):
    name: str
    description: str = ""


class UpdatePageRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[str] = None


class CreateBookmarkRequest(BaseModel):
    name: str
    url: str
    description: str = ""
    parent_id: Optional[str] = None


class CreateFolderRequest(BaseModel):
    name: str
    description: str = ""
    parent_id: Optional[str] = None

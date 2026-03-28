from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class PageInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    name: str
    description: str = ""
    content_type: Literal["html", "url", "folder", "bundle"] = "html"
    parent_id: Optional[str] = None   # null = root level
    filename: Optional[str] = None
    size_bytes: int = 0
    entry_file: Optional[str] = None  # bundle entry point (e.g. "index.html")
    url: Optional[str] = None
    frameable: Optional[bool] = None
    published: bool = False
    host_password_hash: Optional[str] = None  # SHA-256 hash for hosted page access


class CreatePageRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    name: str
    description: str = ""


class UpdatePageRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    name: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[str] = None


class CreateBookmarkRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    name: str
    url: str
    description: str = ""
    parent_id: Optional[str] = None


class CreateFolderRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    name: str
    description: str = ""
    parent_id: Optional[str] = None

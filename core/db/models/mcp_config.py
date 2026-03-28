"""MCP server configuration ORM model."""

from sqlalchemy import String
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class MCPConfigORM(Base):
    __tablename__ = "mcp_configs"

    name: Mapped[str] = mapped_column(String(256), primary_key=True)
    transport: Mapped[str] = mapped_column(String(32), default="stdio")
    command: Mapped[str | None] = mapped_column(String(512), nullable=True)
    args: Mapped[list | None] = mapped_column(JSON, nullable=True)
    env: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)

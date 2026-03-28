"""Skill configuration ORM model."""

from sqlalchemy import String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class SkillConfigORM(Base):
    __tablename__ = "skill_configs"

    name: Mapped[str] = mapped_column(String(256), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    path: Mapped[str] = mapped_column(Text)
    scripts: Mapped[list] = mapped_column(JSON, default=list)
    references: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(default=True)
    license: Mapped[str | None] = mapped_column(String(128), nullable=True)
    compatibility: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    allowed_tools: Mapped[list] = mapped_column(JSON, default=list)
    is_bundled: Mapped[bool] = mapped_column(default=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    created_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(64), nullable=True)

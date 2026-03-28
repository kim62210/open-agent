"""Application settings ORM model (single-row JSON blob)."""

from sqlalchemy import Integer
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class SettingsORM(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    data: Mapped[dict] = mapped_column(JSON)

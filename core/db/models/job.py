"""Job and job run record ORM models."""

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base


class JobORM(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    prompt: Mapped[str] = mapped_column(Text)
    skill_names: Mapped[list] = mapped_column(JSON, default=list)
    mcp_server_names: Mapped[list] = mapped_column(JSON, default=list)
    schedule_type: Mapped[str] = mapped_column(String(32), default="once")
    schedule_config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[str] = mapped_column(String(64))
    next_run_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_run_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_run_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)

    run_records: Mapped[list["JobRunRecordORM"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobRunRecordORM.started_at.desc()",
    )


class JobRunRecordORM(Base):
    __tablename__ = "job_run_records"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE")
    )
    started_at: Mapped[str] = mapped_column(String(64))
    finished_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped["JobORM"] = relationship(back_populates="run_records")

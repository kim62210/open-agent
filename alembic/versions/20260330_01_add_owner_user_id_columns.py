"""add owner_user_id columns

Revision ID: 20260330_01
Revises:
Create Date: 2026-03-30 16:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260330_01"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("owner_user_id", sa.String(length=64), nullable=True))
    op.add_column("memories", sa.Column("owner_user_id", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("owner_user_id", sa.String(length=64), nullable=True))
    op.add_column("workspaces", sa.Column("owner_user_id", sa.String(length=64), nullable=True))
    op.add_column("pages", sa.Column("owner_user_id", sa.String(length=64), nullable=True))

    op.create_index("ix_sessions_owner_user_id", "sessions", ["owner_user_id"], unique=False)
    op.create_index("ix_memories_owner_user_id", "memories", ["owner_user_id"], unique=False)
    op.create_index("ix_jobs_owner_user_id", "jobs", ["owner_user_id"], unique=False)
    op.create_index("ix_workspaces_owner_user_id", "workspaces", ["owner_user_id"], unique=False)
    op.create_index("ix_pages_owner_user_id", "pages", ["owner_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pages_owner_user_id", table_name="pages")
    op.drop_index("ix_workspaces_owner_user_id", table_name="workspaces")
    op.drop_index("ix_jobs_owner_user_id", table_name="jobs")
    op.drop_index("ix_memories_owner_user_id", table_name="memories")
    op.drop_index("ix_sessions_owner_user_id", table_name="sessions")

    op.drop_column("pages", "owner_user_id")
    op.drop_column("workspaces", "owner_user_id")
    op.drop_column("jobs", "owner_user_id")
    op.drop_column("memories", "owner_user_id")
    op.drop_column("sessions", "owner_user_id")

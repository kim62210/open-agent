"""ORM models — re-exports for convenience."""

from core.db.models.job import JobORM, JobRunRecordORM
from core.db.models.mcp_config import MCPConfigORM
from core.db.models.memory import MemoryORM, SessionSummaryORM
from core.db.models.page import PageORM
from core.db.models.run import RunEventORM, RunORM
from core.db.models.session import SessionMessageORM, SessionORM
from core.db.models.settings import SettingsORM
from core.db.models.skill_config import SkillConfigORM
from core.db.models.user import APIKeyORM, RefreshTokenORM, UserORM
from core.db.models.workspace import WorkspaceORM

__all__ = [
    "APIKeyORM",
    "JobORM",
    "JobRunRecordORM",
    "MCPConfigORM",
    "MemoryORM",
    "PageORM",
    "RefreshTokenORM",
    "RunEventORM",
    "RunORM",
    "SessionMessageORM",
    "SessionORM",
    "SessionSummaryORM",
    "SettingsORM",
    "SkillConfigORM",
    "UserORM",
    "WorkspaceORM",
]


def register_all_models() -> None:
    """Import all model modules so Base.metadata knows every table.

    Called by init_db() before create_all().
    """

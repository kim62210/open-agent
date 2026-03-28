"""Workspace repository."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models.workspace import WorkspaceORM
from core.db.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[WorkspaceORM]):
    """Repository for workspace persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, WorkspaceORM)

    async def get_active(self) -> WorkspaceORM | None:
        """Fetch the currently active workspace, if any."""
        stmt = select(WorkspaceORM).where(WorkspaceORM.is_active == True)  # noqa: E712
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_active(self, workspace_id: str) -> None:
        """Deactivate all workspaces, then activate the specified one."""
        await self.session.execute(
            update(WorkspaceORM).values(is_active=False)
        )
        await self.session.execute(
            update(WorkspaceORM)
            .where(WorkspaceORM.id == workspace_id)
            .values(is_active=True)
        )
        await self.session.flush()

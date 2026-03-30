"""Workspace repository."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models.workspace import WorkspaceORM
from core.db.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[WorkspaceORM]):
    """Repository for workspace persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, WorkspaceORM)

    async def get_active(self, owner_user_id: str | None = None) -> WorkspaceORM | None:
        """Fetch the currently active workspace, if any."""
        stmt = select(WorkspaceORM).where(WorkspaceORM.is_active == True)  # noqa: E712
        if owner_user_id is not None:
            stmt = stmt.where(WorkspaceORM.owner_user_id == owner_user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_active(self, workspace_id: str, owner_user_id: str | None = None) -> None:
        deactivate_stmt = update(WorkspaceORM).values(is_active=False)
        if owner_user_id is not None:
            deactivate_stmt = deactivate_stmt.where(WorkspaceORM.owner_user_id == owner_user_id)
        await self.session.execute(deactivate_stmt)

        activate_stmt = update(WorkspaceORM).where(WorkspaceORM.id == workspace_id)
        if owner_user_id is not None:
            activate_stmt = activate_stmt.where(WorkspaceORM.owner_user_id == owner_user_id)
        await self.session.execute(activate_stmt.values(is_active=True))
        await self.session.flush()

"""Memory repository with search and bulk operations."""

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models.memory import MemoryORM, SessionSummaryORM
from core.db.repositories.base import BaseRepository


class MemoryRepository(BaseRepository[MemoryORM]):
    """Repository for memory item persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, MemoryORM)

    async def search(self, keyword: str) -> list[MemoryORM]:
        """Search memories by content substring match."""
        stmt = select(MemoryORM).where(MemoryORM.content.contains(keyword))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_category(self, category: str) -> list[MemoryORM]:
        """Fetch all memories in a specific category."""
        stmt = select(MemoryORM).where(MemoryORM.category == category)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def clear_non_pinned(self, owner_user_id: str | None = None) -> int:
        """Delete all memories that are not pinned. Returns count deleted."""
        stmt = delete(MemoryORM).where(MemoryORM.is_pinned == False)  # noqa: E712
        if owner_user_id is not None:
            stmt = stmt.where(MemoryORM.owner_user_id == owner_user_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def increment_access_count(self, memory_id: str) -> None:
        """Bump the access counter for a memory."""
        stmt = (
            update(MemoryORM)
            .where(MemoryORM.id == memory_id)
            .values(access_count=MemoryORM.access_count + 1)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    # --- Session summaries ---

    async def get_summary(self, session_id: str) -> SessionSummaryORM | None:
        """Fetch summary for a session."""
        return await self.session.get(SessionSummaryORM, session_id)

    async def save_summary(self, summary: SessionSummaryORM) -> SessionSummaryORM:
        """Insert or update a session summary."""
        merged = await self.session.merge(summary)
        await self.session.flush()
        return merged

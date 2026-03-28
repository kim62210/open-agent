"""Page repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models.page import PageORM
from core.db.repositories.base import BaseRepository


class PageRepository(BaseRepository[PageORM]):
    """Repository for page persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PageORM)

    async def get_by_parent(self, parent_id: str | None) -> list[PageORM]:
        """Fetch all pages under a given parent (None = root level)."""
        if parent_id is None:
            stmt = select(PageORM).where(PageORM.parent_id.is_(None))
        else:
            stmt = select(PageORM).where(PageORM.parent_id == parent_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_content_type(self, content_type: str) -> list[PageORM]:
        """Fetch all pages of a specific content type."""
        stmt = select(PageORM).where(PageORM.content_type == content_type)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_published(self) -> list[PageORM]:
        """Fetch all published pages."""
        stmt = select(PageORM).where(PageORM.published == True)  # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

"""MCP server configuration repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models.mcp_config import MCPConfigORM
from core.db.repositories.base import BaseRepository


class MCPConfigRepository(BaseRepository[MCPConfigORM]):
    """Repository for MCP server configuration persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, MCPConfigORM)

    async def get_by_name(self, name: str) -> MCPConfigORM | None:
        """Fetch an MCP server config by its name (primary key)."""
        return await self.get_by_id(name)

    async def get_enabled(self) -> list[MCPConfigORM]:
        """Fetch all enabled MCP server configs."""
        stmt = select(MCPConfigORM).where(MCPConfigORM.enabled == True)  # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

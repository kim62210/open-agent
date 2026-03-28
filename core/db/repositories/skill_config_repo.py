"""Skill configuration repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models.skill_config import SkillConfigORM
from core.db.repositories.base import BaseRepository


class SkillConfigRepository(BaseRepository[SkillConfigORM]):
    """Repository for skill configuration persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SkillConfigORM)

    async def get_by_name(self, name: str) -> SkillConfigORM | None:
        """Fetch a skill config by its name (primary key)."""
        return await self.get_by_id(name)

    async def get_enabled(self) -> list[SkillConfigORM]:
        """Fetch all enabled skill configs."""
        stmt = select(SkillConfigORM).where(SkillConfigORM.enabled == True)  # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_disabled_names(self) -> list[str]:
        """Return names of all disabled skills."""
        stmt = select(SkillConfigORM.name).where(
            SkillConfigORM.enabled == False  # noqa: E712
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

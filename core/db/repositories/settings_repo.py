"""Settings repository (single-row JSON blob)."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models.settings import SettingsORM
from core.db.repositories.base import BaseRepository


class SettingsRepository(BaseRepository[SettingsORM]):
    """Repository for application settings (single row, id=1)."""

    SINGLETON_ID = 1

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SettingsORM)

    async def get_settings(self) -> dict | None:
        """Return the settings JSON dict, or None if not yet initialized."""
        row = await self.get_by_id(self.SINGLETON_ID)
        if row is None:
            return None
        return row.data

    async def save_settings(self, data: dict) -> SettingsORM:
        """Insert or update the singleton settings row."""
        row = await self.get_by_id(self.SINGLETON_ID)
        if row is None:
            row = SettingsORM(id=self.SINGLETON_ID, data=data)
            self.session.add(row)
        else:
            row.data = data
        await self.session.flush()
        return row

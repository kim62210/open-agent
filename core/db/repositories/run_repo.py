from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.db.models.run import RunEventORM, RunORM
from core.db.repositories.base import BaseRepository


class RunRepository(BaseRepository[RunORM]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RunORM)

    async def get_with_events(self, run_id: str, owner_user_id: str | None = None) -> RunORM | None:
        stmt = select(RunORM).where(RunORM.id == run_id).options(selectinload(RunORM.events))
        if owner_user_id is not None:
            stmt = stmt.where(RunORM.owner_user_id == owner_user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_owner(self, owner_user_id: str) -> list[RunORM]:
        stmt = (
            select(RunORM)
            .where(RunORM.owner_user_id == owner_user_id)
            .order_by(RunORM.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def next_event_seq(self, run_id: str) -> int:
        stmt = select(func.count()).select_from(RunEventORM).where(RunEventORM.run_id == run_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def add_event(self, event: RunEventORM) -> RunEventORM:
        self.session.add(event)
        await self.session.flush()
        return event

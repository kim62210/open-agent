"""Session repository with message management."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.db.models.session import SessionMessageORM, SessionORM
from core.db.repositories.base import BaseRepository


class SessionRepository(BaseRepository[SessionORM]):
    """Repository for session and message persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SessionORM)

    async def get_with_messages(self, session_id: str) -> SessionORM | None:
        """Fetch a session with all its messages eagerly loaded."""
        stmt = (
            select(SessionORM)
            .where(SessionORM.id == session_id)
            .options(selectinload(SessionORM.messages))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def save_messages(
        self,
        session_id: str,
        messages: list[SessionMessageORM],
    ) -> None:
        """Replace all messages for a session (delete + bulk insert)."""
        await self.session.execute(
            delete(SessionMessageORM).where(
                SessionMessageORM.session_id == session_id
            )
        )
        for seq, msg in enumerate(messages):
            msg.session_id = session_id
            msg.seq = seq
            self.session.add(msg)
        await self.session.flush()

    async def get_all_ordered(self) -> list[SessionORM]:
        """Fetch all sessions ordered by updated_at descending."""
        stmt = select(SessionORM).order_by(SessionORM.updated_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_preview(
        self,
        session_id: str,
        preview: str,
        message_count: int,
        updated_at: str,
    ) -> None:
        """Update session metadata after messages change."""
        obj = await self.get_by_id(session_id)
        if obj:
            obj.preview = preview
            obj.message_count = message_count
            obj.updated_at = updated_at
            await self.session.flush()

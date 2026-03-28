"""Base repository with common CRUD operations."""

from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Generic async repository providing basic CRUD."""

    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        self.session = session
        self.model = model

    async def get_by_id(self, id: str | int) -> T | None:
        """Fetch a single row by primary key."""
        return await self.session.get(self.model, id)

    async def get_all(self) -> list[T]:
        """Fetch all rows for this model."""
        result = await self.session.execute(select(self.model))
        return list(result.scalars().all())

    async def create(self, obj: T) -> T:
        """Add a new row and flush to obtain defaults / generated keys."""
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update(self, obj: T) -> T:
        """Merge a detached/modified instance back into the session."""
        merged = await self.session.merge(obj)
        await self.session.flush()
        return merged

    async def delete_by_id(self, id: str | int) -> bool:
        """Delete a row by primary key. Returns True if it existed."""
        obj = await self.get_by_id(id)
        if obj:
            await self.session.delete(obj)
            await self.session.flush()
            return True
        return False

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self.session.commit()

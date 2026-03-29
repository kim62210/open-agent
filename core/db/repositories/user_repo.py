"""User, API key, and refresh token repositories."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models.user import APIKeyORM, RefreshTokenORM, UserORM
from core.db.repositories.base import BaseRepository


class UserRepository(BaseRepository[UserORM]):
    """Repository for user persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, UserORM)

    async def get_by_email(self, email: str) -> UserORM | None:
        """Fetch a user by email address."""
        stmt = select(UserORM).where(UserORM.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> UserORM | None:
        """Fetch a user by username."""
        stmt = select(UserORM).where(UserORM.username == username)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_all(self) -> int:
        """Return total number of users."""
        stmt = select(func.count()).select_from(UserORM)
        result = await self.session.execute(stmt)
        return result.scalar_one()


class APIKeyRepository(BaseRepository[APIKeyORM]):
    """Repository for API key persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, APIKeyORM)

    async def get_by_user_id(self, user_id: str) -> list[APIKeyORM]:
        """Fetch all API keys belonging to a user."""
        stmt = (
            select(APIKeyORM)
            .where(APIKeyORM.user_id == user_id)
            .order_by(APIKeyORM.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_key_hash(self, key_hash: str) -> APIKeyORM | None:
        """Fetch an API key by its hash."""
        stmt = select(APIKeyORM).where(APIKeyORM.key_hash == key_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class RefreshTokenRepository(BaseRepository[RefreshTokenORM]):
    """Repository for refresh token persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RefreshTokenORM)

    async def get_by_user_id(self, user_id: str) -> list[RefreshTokenORM]:
        """Fetch all refresh tokens belonging to a user."""
        stmt = (
            select(RefreshTokenORM)
            .where(RefreshTokenORM.user_id == user_id, RefreshTokenORM.is_revoked.is_(False))
            .order_by(RefreshTokenORM.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def revoke_all_for_user(self, user_id: str) -> int:
        """Revoke all active refresh tokens for a user. Returns count revoked."""
        tokens = await self.get_by_user_id(user_id)
        count = 0
        for token in tokens:
            token.is_revoked = True
            count += 1
        if count:
            await self.session.flush()
        return count

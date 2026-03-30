"""DB repository unit tests — BaseRepository CRUD, UserRepo, SessionRepo, MemoryRepo, SettingsRepo."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.db.base import Base


@pytest.fixture()
async def repo_engine():
    """In-memory SQLite engine for repository tests."""
    from core.db.models import register_all_models
    register_all_models()

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def repo_session(repo_engine):
    """Async session for repository tests."""
    factory = async_sessionmaker(repo_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


class TestBaseRepository:
    """BaseRepository CRUD operations."""

    async def test_create_and_get_by_id(self, repo_session):
        """Create and retrieve a record by ID."""
        from core.db.models.user import UserORM
        from core.db.repositories.base import BaseRepository

        repo = BaseRepository(repo_session, UserORM)
        now = datetime.now(timezone.utc).isoformat()
        user = UserORM(
            id="test-1", email="test@test.com", username="testuser",
            password_hash="hash", role="user", is_active=True,
            created_at=now, updated_at=now,
        )
        await repo.create(user)
        await repo_session.commit()

        fetched = await repo.get_by_id("test-1")
        assert fetched is not None
        assert fetched.email == "test@test.com"

    async def test_get_all(self, repo_session):
        """Fetch all records."""
        from core.db.models.user import UserORM
        from core.db.repositories.base import BaseRepository

        repo = BaseRepository(repo_session, UserORM)
        now = datetime.now(timezone.utc).isoformat()
        for i in range(3):
            user = UserORM(
                id=f"user-{i}", email=f"u{i}@test.com", username=f"user{i}",
                password_hash="hash", role="user", is_active=True,
                created_at=now, updated_at=now,
            )
            await repo.create(user)
        await repo_session.commit()

        all_users = await repo.get_all()
        assert len(all_users) == 3

    async def test_delete_by_id(self, repo_session):
        """Delete a record by ID."""
        from core.db.models.user import UserORM
        from core.db.repositories.base import BaseRepository

        repo = BaseRepository(repo_session, UserORM)
        now = datetime.now(timezone.utc).isoformat()
        user = UserORM(
            id="del-1", email="del@test.com", username="deluser",
            password_hash="hash", role="user", is_active=True,
            created_at=now, updated_at=now,
        )
        await repo.create(user)
        await repo_session.commit()

        deleted = await repo.delete_by_id("del-1")
        assert deleted is True
        await repo_session.commit()

        fetched = await repo.get_by_id("del-1")
        assert fetched is None

    async def test_delete_nonexistent_returns_false(self, repo_session):
        """Deleting non-existent record returns False."""
        from core.db.models.user import UserORM
        from core.db.repositories.base import BaseRepository

        repo = BaseRepository(repo_session, UserORM)
        deleted = await repo.delete_by_id("nonexistent")
        assert deleted is False

    async def test_update(self, repo_session):
        """Update a record via merge."""
        from core.db.models.user import UserORM
        from core.db.repositories.base import BaseRepository

        repo = BaseRepository(repo_session, UserORM)
        now = datetime.now(timezone.utc).isoformat()
        user = UserORM(
            id="upd-1", email="upd@test.com", username="upduser",
            password_hash="hash", role="user", is_active=True,
            created_at=now, updated_at=now,
        )
        await repo.create(user)
        await repo_session.commit()

        user.role = "admin"
        merged = await repo.update(user)
        await repo_session.commit()

        fetched = await repo.get_by_id("upd-1")
        assert fetched.role == "admin"


class TestUserRepository:
    """UserRepository-specific operations."""

    async def test_get_by_email(self, repo_session):
        """Fetch user by email."""
        from core.db.models.user import UserORM
        from core.db.repositories.user_repo import UserRepository

        repo = UserRepository(repo_session)
        now = datetime.now(timezone.utc).isoformat()
        user = UserORM(
            id="u-email", email="email@test.com", username="emailuser",
            password_hash="hash", role="user", is_active=True,
            created_at=now, updated_at=now,
        )
        await repo.create(user)
        await repo_session.commit()

        fetched = await repo.get_by_email("email@test.com")
        assert fetched is not None
        assert fetched.id == "u-email"

    async def test_get_by_email_not_found(self, repo_session):
        """Returns None for non-existent email."""
        from core.db.repositories.user_repo import UserRepository
        repo = UserRepository(repo_session)
        result = await repo.get_by_email("nobody@test.com")
        assert result is None

    async def test_get_by_username(self, repo_session):
        """Fetch user by username."""
        from core.db.models.user import UserORM
        from core.db.repositories.user_repo import UserRepository

        repo = UserRepository(repo_session)
        now = datetime.now(timezone.utc).isoformat()
        user = UserORM(
            id="u-uname", email="uname@test.com", username="uniquename",
            password_hash="hash", role="user", is_active=True,
            created_at=now, updated_at=now,
        )
        await repo.create(user)
        await repo_session.commit()

        fetched = await repo.get_by_username("uniquename")
        assert fetched is not None

    async def test_count_all(self, repo_session):
        """Count all users."""
        from core.db.models.user import UserORM
        from core.db.repositories.user_repo import UserRepository

        repo = UserRepository(repo_session)
        now = datetime.now(timezone.utc).isoformat()
        for i in range(2):
            user = UserORM(
                id=f"cnt-{i}", email=f"cnt{i}@test.com", username=f"cnt{i}",
                password_hash="hash", role="user", is_active=True,
                created_at=now, updated_at=now,
            )
            await repo.create(user)
        await repo_session.commit()

        count = await repo.count_all()
        assert count == 2


class TestSessionRepository:
    """SessionRepository operations."""

    async def test_get_all_ordered(self, repo_session):
        """Fetch sessions ordered by updated_at desc."""
        from core.db.models.session import SessionORM
        from core.db.repositories.session_repo import SessionRepository

        repo = SessionRepository(repo_session)
        for i in range(3):
            s = SessionORM(
                id=f"sess-{i}", title=f"Session {i}",
                created_at=f"2024-01-0{i+1}T00:00:00Z",
                updated_at=f"2024-01-0{i+1}T00:00:00Z",
                message_count=0, preview="",
            )
            await repo.create(s)
        await repo_session.commit()

        sessions = await repo.get_all_ordered()
        assert len(sessions) == 3
        # Most recently updated first
        assert sessions[0].id == "sess-2"

    async def test_save_messages(self, repo_session):
        """Save messages replaces existing."""
        from core.db.models.session import SessionMessageORM, SessionORM
        from core.db.repositories.session_repo import SessionRepository

        repo = SessionRepository(repo_session)
        s = SessionORM(
            id="msg-sess", title="Message Test",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
            message_count=0, preview="",
        )
        await repo.create(s)
        await repo_session.commit()

        msgs = [
            SessionMessageORM(role="user", content="Hello"),
            SessionMessageORM(role="assistant", content="Hi"),
        ]
        await repo.save_messages("msg-sess", msgs)
        await repo_session.commit()

        loaded = await repo.get_with_messages("msg-sess")
        assert loaded is not None
        assert len(loaded.messages) == 2


class TestMemoryRepository:
    """MemoryRepository operations."""

    async def test_search(self, repo_session):
        """Search memories by keyword."""
        from core.db.models.memory import MemoryORM
        from core.db.repositories.memory_repo import MemoryRepository

        repo = MemoryRepository(repo_session)
        now = datetime.now(timezone.utc).isoformat()
        m1 = MemoryORM(
            id="m1", content="Python is great", category="fact",
            confidence=0.9, source="llm_inference", is_pinned=False,
            access_count=0, created_at=now, updated_at=now,
        )
        m2 = MemoryORM(
            id="m2", content="Rust is fast", category="fact",
            confidence=0.8, source="llm_inference", is_pinned=False,
            access_count=0, created_at=now, updated_at=now,
        )
        await repo.create(m1)
        await repo.create(m2)
        await repo_session.commit()

        results = await repo.search("Python")
        assert len(results) == 1
        assert results[0].id == "m1"

    async def test_get_by_category(self, repo_session):
        """Fetch memories by category."""
        from core.db.models.memory import MemoryORM
        from core.db.repositories.memory_repo import MemoryRepository

        repo = MemoryRepository(repo_session)
        now = datetime.now(timezone.utc).isoformat()
        m1 = MemoryORM(
            id="cat1", content="Preference", category="preference",
            confidence=0.7, source="user_input", is_pinned=False,
            access_count=0, created_at=now, updated_at=now,
        )
        m2 = MemoryORM(
            id="cat2", content="Fact", category="fact",
            confidence=0.7, source="llm_inference", is_pinned=False,
            access_count=0, created_at=now, updated_at=now,
        )
        await repo.create(m1)
        await repo.create(m2)
        await repo_session.commit()

        results = await repo.get_by_category("preference")
        assert len(results) == 1

    async def test_increment_access_count(self, repo_session):
        """Bump access counter."""
        from core.db.models.memory import MemoryORM
        from core.db.repositories.memory_repo import MemoryRepository

        repo = MemoryRepository(repo_session)
        now = datetime.now(timezone.utc).isoformat()
        m = MemoryORM(
            id="acc1", content="Test", category="fact",
            confidence=0.7, source="llm_inference", is_pinned=False,
            access_count=0, created_at=now, updated_at=now,
        )
        await repo.create(m)
        await repo_session.commit()

        await repo.increment_access_count("acc1")
        await repo_session.commit()

        refreshed = await repo.get_by_id("acc1")
        assert refreshed.access_count == 1


class TestSettingsRepository:
    """SettingsRepository operations."""

    async def test_save_and_get_settings(self, repo_session):
        """Save and retrieve settings."""
        from core.db.repositories.settings_repo import SettingsRepository

        repo = SettingsRepository(repo_session)
        data = {"llm": {"model": "test-model"}, "memory": {"enabled": True}}
        await repo.save_settings(data)
        await repo_session.commit()

        result = await repo.get_settings()
        assert result is not None
        assert result["llm"]["model"] == "test-model"

    async def test_update_existing_settings(self, repo_session):
        """Updating settings overwrites the singleton row."""
        from core.db.repositories.settings_repo import SettingsRepository

        repo = SettingsRepository(repo_session)
        await repo.save_settings({"llm": {"model": "v1"}})
        await repo_session.commit()

        await repo.save_settings({"llm": {"model": "v2"}})
        await repo_session.commit()

        result = await repo.get_settings()
        assert result["llm"]["model"] == "v2"

    async def test_get_settings_empty(self, repo_session):
        """Returns None when no settings saved."""
        from core.db.repositories.settings_repo import SettingsRepository

        repo = SettingsRepository(repo_session)
        result = await repo.get_settings()
        assert result is None

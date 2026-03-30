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


class TestBaseRepositoryCommit:
    """BaseRepository.commit() method."""

    async def test_commit_persists_changes(self, repo_session):
        """commit() flushes transaction to database."""
        from core.db.models.user import UserORM
        from core.db.repositories.base import BaseRepository

        repo = BaseRepository(repo_session, UserORM)
        now = datetime.now(timezone.utc).isoformat()
        user = UserORM(
            id="commit-1", email="commit@test.com", username="commituser",
            password_hash="hash", role="user", is_active=True,
            created_at=now, updated_at=now,
        )
        await repo.create(user)
        await repo.commit()
        fetched = await repo.get_by_id("commit-1")
        assert fetched is not None


class TestAPIKeyRepository:
    """APIKeyRepository operations."""

    async def test_get_by_user_id(self, repo_session):
        """Fetch API keys by user ID."""
        from core.db.models.user import APIKeyORM, UserORM
        from core.db.repositories.user_repo import APIKeyRepository

        now = datetime.now(timezone.utc).isoformat()
        user = UserORM(
            id="akr-user", email="akr@test.com", username="akruser",
            password_hash="hash", role="user", is_active=True,
            created_at=now, updated_at=now,
        )
        repo_session.add(user)
        for i in range(2):
            ak = APIKeyORM(
                id=f"ak-{i}", user_id="akr-user", key_hash=f"hash-{i}",
                key_prefix=f"oa-prefix-{i}", name=f"key-{i}", is_active=True,
                created_at=now, last_used_at=None,
            )
            repo_session.add(ak)
        await repo_session.commit()

        repo = APIKeyRepository(repo_session)
        keys = await repo.get_by_user_id("akr-user")
        assert len(keys) == 2

    async def test_get_by_key_hash(self, repo_session):
        """Fetch API key by hash."""
        from core.db.models.user import APIKeyORM, UserORM
        from core.db.repositories.user_repo import APIKeyRepository

        now = datetime.now(timezone.utc).isoformat()
        user = UserORM(
            id="akh-user", email="akh@test.com", username="akhuser",
            password_hash="hash", role="user", is_active=True,
            created_at=now, updated_at=now,
        )
        repo_session.add(user)
        ak = APIKeyORM(
            id="ak-hash", user_id="akh-user", key_hash="unique-hash-123",
            key_prefix="oa-prefix", name="hash-key", is_active=True,
            created_at=now, last_used_at=None,
        )
        repo_session.add(ak)
        await repo_session.commit()

        repo = APIKeyRepository(repo_session)
        found = await repo.get_by_key_hash("unique-hash-123")
        assert found is not None
        assert found.id == "ak-hash"

    async def test_get_by_key_hash_not_found(self, repo_session):
        """Returns None for nonexistent key hash."""
        from core.db.repositories.user_repo import APIKeyRepository

        repo = APIKeyRepository(repo_session)
        result = await repo.get_by_key_hash("nonexistent-hash")
        assert result is None


class TestRefreshTokenRepository:
    """RefreshTokenRepository operations."""

    async def test_get_by_user_id(self, repo_session):
        """Fetch active refresh tokens for a user."""
        from core.db.models.user import RefreshTokenORM, UserORM
        from core.db.repositories.user_repo import RefreshTokenRepository

        now = datetime.now(timezone.utc).isoformat()
        user = UserORM(
            id="rt-user", email="rt@test.com", username="rtuser",
            password_hash="hash", role="user", is_active=True,
            created_at=now, updated_at=now,
        )
        repo_session.add(user)
        for i in range(3):
            rt = RefreshTokenORM(
                id=f"rt-{i}", user_id="rt-user", token_hash=f"thash-{i}",
                is_revoked=(i == 2), created_at=now,
            )
            repo_session.add(rt)
        await repo_session.commit()

        repo = RefreshTokenRepository(repo_session)
        tokens = await repo.get_by_user_id("rt-user")
        # Only non-revoked tokens
        assert len(tokens) == 2

    async def test_revoke_all_for_user(self, repo_session):
        """Revoke all tokens for a user."""
        from core.db.models.user import RefreshTokenORM, UserORM
        from core.db.repositories.user_repo import RefreshTokenRepository

        now = datetime.now(timezone.utc).isoformat()
        user = UserORM(
            id="rta-user", email="rta@test.com", username="rtauser",
            password_hash="hash", role="user", is_active=True,
            created_at=now, updated_at=now,
        )
        repo_session.add(user)
        for i in range(3):
            rt = RefreshTokenORM(
                id=f"rta-{i}", user_id="rta-user", token_hash=f"rtahash-{i}",
                is_revoked=False, created_at=now,
            )
            repo_session.add(rt)
        await repo_session.commit()

        repo = RefreshTokenRepository(repo_session)
        count = await repo.revoke_all_for_user("rta-user")
        assert count == 3
        await repo_session.commit()

        remaining = await repo.get_by_user_id("rta-user")
        assert len(remaining) == 0


class TestSessionRepositoryExtended:
    """Additional SessionRepository tests."""

    async def test_update_preview(self, repo_session):
        """Update session preview and metadata."""
        from core.db.models.session import SessionORM
        from core.db.repositories.session_repo import SessionRepository

        repo = SessionRepository(repo_session)
        s = SessionORM(
            id="prev-sess", title="Preview Test",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
            message_count=0, preview="",
        )
        await repo.create(s)
        await repo_session.commit()

        await repo.update_preview("prev-sess", "Hello world", 5, "2024-01-02T00:00:00Z")
        await repo_session.commit()

        fetched = await repo.get_by_id("prev-sess")
        assert fetched.preview == "Hello world"
        assert fetched.message_count == 5
        assert fetched.updated_at == "2024-01-02T00:00:00Z"

    async def test_update_preview_nonexistent_noop(self, repo_session):
        """update_preview on nonexistent session does nothing."""
        from core.db.repositories.session_repo import SessionRepository

        repo = SessionRepository(repo_session)
        await repo.update_preview("nonexistent", "test", 0, "2024-01-01T00:00:00Z")
        await repo_session.commit()


class TestMemoryRepositoryExtended:
    """Additional MemoryRepository tests."""

    async def test_clear_non_pinned(self, repo_session):
        """Delete all non-pinned memories."""
        from core.db.models.memory import MemoryORM
        from core.db.repositories.memory_repo import MemoryRepository

        repo = MemoryRepository(repo_session)
        now = datetime.now(timezone.utc).isoformat()
        m1 = MemoryORM(
            id="pin1", content="Pinned", category="fact",
            confidence=0.9, source="user_input", is_pinned=True,
            access_count=0, created_at=now, updated_at=now,
        )
        m2 = MemoryORM(
            id="unpin1", content="Unpinned", category="fact",
            confidence=0.5, source="llm_inference", is_pinned=False,
            access_count=0, created_at=now, updated_at=now,
        )
        await repo.create(m1)
        await repo.create(m2)
        await repo_session.commit()

        deleted = await repo.clear_non_pinned()
        assert deleted == 1
        await repo_session.commit()

        all_memories = await repo.get_all()
        assert len(all_memories) == 1
        assert all_memories[0].id == "pin1"

    async def test_save_and_get_summary(self, repo_session):
        """Save and retrieve a session summary."""
        from core.db.models.memory import SessionSummaryORM
        from core.db.repositories.memory_repo import MemoryRepository

        repo = MemoryRepository(repo_session)
        summary = SessionSummaryORM(
            session_id="summ-sess",
            summary="This session discussed Python testing.",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        await repo.save_summary(summary)
        await repo_session.commit()

        fetched = await repo.get_summary("summ-sess")
        assert fetched is not None
        assert "Python testing" in fetched.summary

    async def test_get_summary_not_found(self, repo_session):
        """Returns None for nonexistent session summary."""
        from core.db.repositories.memory_repo import MemoryRepository

        repo = MemoryRepository(repo_session)
        result = await repo.get_summary("nonexistent-sess")
        assert result is None


class TestJobRepository:
    """JobRepository operations."""

    async def test_get_enabled_jobs(self, repo_session):
        """Fetch only enabled jobs."""
        from core.db.models.job import JobORM
        from core.db.repositories.job_repo import JobRepository

        repo = JobRepository(repo_session)
        now = datetime.now(timezone.utc).isoformat()
        for i, enabled in enumerate([True, True, False]):
            job = JobORM(
                id=f"job-{i}", name=f"Job {i}", prompt="Do something",
                schedule_type="once", enabled=enabled,
                created_at=now, updated_at=now,
            )
            await repo.create(job)
        await repo_session.commit()

        enabled_jobs = await repo.get_enabled_jobs()
        assert len(enabled_jobs) == 2

    async def test_add_and_get_run_records(self, repo_session):
        """Add run records and retrieve them."""
        from core.db.models.job import JobORM, JobRunRecordORM
        from core.db.repositories.job_repo import JobRepository

        repo = JobRepository(repo_session)
        now = datetime.now(timezone.utc).isoformat()
        job = JobORM(
            id="rr-job", name="Record Job", prompt="Test",
            schedule_type="once", enabled=True,
            created_at=now, updated_at=now,
        )
        await repo.create(job)
        await repo_session.commit()

        record = JobRunRecordORM(
            run_id="run-1", job_id="rr-job",
            started_at=now, status="success",
        )
        await repo.add_run_record(record)
        await repo_session.commit()

        records = await repo.get_run_records("rr-job")
        assert len(records) == 1
        assert records[0].status == "success"

    async def test_get_with_records(self, repo_session):
        """Fetch job with eagerly loaded run records."""
        from core.db.models.job import JobORM, JobRunRecordORM
        from core.db.repositories.job_repo import JobRepository

        repo = JobRepository(repo_session)
        now = datetime.now(timezone.utc).isoformat()
        job = JobORM(
            id="wr-job", name="With Records", prompt="Test",
            schedule_type="once", enabled=True,
            created_at=now, updated_at=now,
        )
        await repo.create(job)
        record = JobRunRecordORM(
            run_id="wr-run-1", job_id="wr-job",
            started_at=now, status="running",
        )
        await repo.add_run_record(record)
        await repo_session.commit()

        loaded = await repo.get_with_records("wr-job")
        assert loaded is not None
        assert len(loaded.run_records) == 1


class TestMCPConfigRepository:
    """MCPConfigRepository operations."""

    async def test_get_by_name(self, repo_session):
        """Fetch MCP config by name."""
        from core.db.models.mcp_config import MCPConfigORM
        from core.db.repositories.mcp_config_repo import MCPConfigRepository

        repo = MCPConfigRepository(repo_session)
        config = MCPConfigORM(
            name="test-server", transport="stdio",
            command="npx", args=["-y", "test-mcp"],
            enabled=True,
        )
        await repo.create(config)
        await repo_session.commit()

        fetched = await repo.get_by_name("test-server")
        assert fetched is not None
        assert fetched.transport == "stdio"

    async def test_get_enabled(self, repo_session):
        """Fetch only enabled MCP configs."""
        from core.db.models.mcp_config import MCPConfigORM
        from core.db.repositories.mcp_config_repo import MCPConfigRepository

        repo = MCPConfigRepository(repo_session)
        for i, enabled in enumerate([True, False, True]):
            config = MCPConfigORM(
                name=f"server-{i}", transport="stdio",
                command="test", enabled=enabled,
            )
            await repo.create(config)
        await repo_session.commit()

        enabled = await repo.get_enabled()
        assert len(enabled) == 2


class TestPageRepository:
    """PageRepository operations."""

    async def test_get_by_parent(self, repo_session):
        """Fetch pages by parent ID."""
        from core.db.models.page import PageORM
        from core.db.repositories.page_repo import PageRepository

        repo = PageRepository(repo_session)
        root = PageORM(
            id="root-page", name="Root", content_type="html",
            parent_id=None, published=False,
        )
        child = PageORM(
            id="child-page", name="Child", content_type="html",
            parent_id="root-page", published=False,
        )
        await repo.create(root)
        await repo.create(child)
        await repo_session.commit()

        root_pages = await repo.get_by_parent(None)
        assert len(root_pages) == 1
        assert root_pages[0].id == "root-page"

        children = await repo.get_by_parent("root-page")
        assert len(children) == 1

    async def test_get_published(self, repo_session):
        """Fetch published pages."""
        from core.db.models.page import PageORM
        from core.db.repositories.page_repo import PageRepository

        repo = PageRepository(repo_session)
        for i, pub in enumerate([True, False, True]):
            p = PageORM(
                id=f"pub-{i}", name=f"Page {i}", content_type="html",
                published=pub,
            )
            await repo.create(p)
        await repo_session.commit()

        published = await repo.get_published()
        assert len(published) == 2

    async def test_get_by_content_type(self, repo_session):
        """Fetch pages by content type."""
        from core.db.models.page import PageORM
        from core.db.repositories.page_repo import PageRepository

        repo = PageRepository(repo_session)
        for i, ctype in enumerate(["html", "html", "bundle"]):
            p = PageORM(
                id=f"ct-{i}", name=f"Page {i}", content_type=ctype,
            )
            await repo.create(p)
        await repo_session.commit()

        html_pages = await repo.get_by_content_type("html")
        assert len(html_pages) == 2
        bundle_pages = await repo.get_by_content_type("bundle")
        assert len(bundle_pages) == 1


class TestSkillConfigRepository:
    """SkillConfigRepository operations."""

    async def test_get_by_name(self, repo_session):
        """Fetch skill config by name."""
        from core.db.models.skill_config import SkillConfigORM
        from core.db.repositories.skill_config_repo import SkillConfigRepository

        repo = SkillConfigRepository(repo_session)
        skill = SkillConfigORM(
            name="test-skill", description="A test skill",
            path="/skills/test", enabled=True,
        )
        await repo.create(skill)
        await repo_session.commit()

        fetched = await repo.get_by_name("test-skill")
        assert fetched is not None
        assert fetched.description == "A test skill"

    async def test_get_enabled(self, repo_session):
        """Fetch only enabled skills."""
        from core.db.models.skill_config import SkillConfigORM
        from core.db.repositories.skill_config_repo import SkillConfigRepository

        repo = SkillConfigRepository(repo_session)
        for i, enabled in enumerate([True, False, True]):
            skill = SkillConfigORM(
                name=f"skill-{i}", description="", path=f"/skills/{i}",
                enabled=enabled,
            )
            await repo.create(skill)
        await repo_session.commit()

        enabled = await repo.get_enabled()
        assert len(enabled) == 2

    async def test_get_disabled_names(self, repo_session):
        """Get names of disabled skills."""
        from core.db.models.skill_config import SkillConfigORM
        from core.db.repositories.skill_config_repo import SkillConfigRepository

        repo = SkillConfigRepository(repo_session)
        for i, enabled in enumerate([True, False, False]):
            skill = SkillConfigORM(
                name=f"dn-skill-{i}", description="", path=f"/skills/{i}",
                enabled=enabled,
            )
            await repo.create(skill)
        await repo_session.commit()

        disabled = await repo.get_disabled_names()
        assert len(disabled) == 2
        assert "dn-skill-1" in disabled
        assert "dn-skill-2" in disabled


class TestWorkspaceRepository:
    """WorkspaceRepository operations."""

    async def test_get_active(self, repo_session):
        """Fetch the active workspace."""
        from core.db.models.workspace import WorkspaceORM
        from core.db.repositories.workspace_repo import WorkspaceRepository

        repo = WorkspaceRepository(repo_session)
        now = datetime.now(timezone.utc).isoformat()
        for i, active in enumerate([False, True, False]):
            ws = WorkspaceORM(
                id=f"ws-{i}", name=f"WS {i}", path=f"/path/{i}",
                created_at=now, is_active=active,
            )
            await repo.create(ws)
        await repo_session.commit()

        active = await repo.get_active()
        assert active is not None
        assert active.id == "ws-1"

    async def test_get_active_none(self, repo_session):
        """Returns None when no active workspace."""
        from core.db.repositories.workspace_repo import WorkspaceRepository

        repo = WorkspaceRepository(repo_session)
        result = await repo.get_active()
        assert result is None

    async def test_set_active(self, repo_session):
        """Activate a specific workspace, deactivating others."""
        from core.db.models.workspace import WorkspaceORM
        from core.db.repositories.workspace_repo import WorkspaceRepository

        repo = WorkspaceRepository(repo_session)
        now = datetime.now(timezone.utc).isoformat()
        for i in range(3):
            ws = WorkspaceORM(
                id=f"sa-ws-{i}", name=f"WS {i}", path=f"/path/{i}",
                created_at=now, is_active=(i == 0),
            )
            await repo.create(ws)
        await repo_session.commit()

        await repo.set_active("sa-ws-2")
        await repo_session.commit()

        active = await repo.get_active()
        assert active is not None
        assert active.id == "sa-ws-2"


class TestRepositoryInit:
    """Repository __init__.py re-exports."""

    def test_all_exports(self):
        """All expected repository classes are importable."""
        from core.db.repositories import (
            BaseRepository,
            JobRepository,
            MCPConfigRepository,
            MemoryRepository,
            PageRepository,
            SessionRepository,
            SettingsRepository,
            SkillConfigRepository,
            WorkspaceRepository,
        )

        assert BaseRepository is not None
        assert JobRepository is not None
        assert MCPConfigRepository is not None
        assert MemoryRepository is not None
        assert PageRepository is not None
        assert SessionRepository is not None
        assert SettingsRepository is not None
        assert SkillConfigRepository is not None
        assert WorkspaceRepository is not None

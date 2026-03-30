"""DB engine and models registration tests."""

import os
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncEngine


class TestBuildDatabaseUrl:
    """_build_database_url() in core.db.engine."""

    def test_default_sqlite(self):
        """Without DATABASE_URL, defaults to SQLite."""
        from core.db.engine import _build_database_url

        with patch.dict(os.environ, {}, clear=False):
            if "DATABASE_URL" in os.environ:
                del os.environ["DATABASE_URL"]
            url = _build_database_url()
        assert "sqlite+aiosqlite" in url

    def test_postgres_url_conversion(self):
        """postgres:// is converted to postgresql+asyncpg://."""
        from core.db.engine import _build_database_url

        with patch.dict(os.environ, {"DATABASE_URL": "postgres://user:pass@host/db"}):
            url = _build_database_url()
        assert url.startswith("postgresql+asyncpg://")

    def test_postgresql_url_conversion(self):
        """postgresql:// is converted to postgresql+asyncpg://."""
        from core.db.engine import _build_database_url

        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@host/db"}):
            url = _build_database_url()
        assert url.startswith("postgresql+asyncpg://")

    def test_custom_database_url_passthrough(self):
        """Non-postgres URLs are passed through unchanged."""
        from core.db.engine import _build_database_url

        with patch.dict(os.environ, {"DATABASE_URL": "mysql+asyncmy://user:pass@host/db"}):
            url = _build_database_url()
        assert url == "mysql+asyncmy://user:pass@host/db"


class TestCreateEngine:
    """_create_engine() in core.db.engine."""

    def test_returns_async_engine(self):
        """Creates an AsyncEngine instance."""
        from core.db.engine import _create_engine

        engine = _create_engine()
        assert isinstance(engine, AsyncEngine)


class TestModuleLevelEngine:
    """Module-level engine and session factory."""

    def test_engine_exists(self):
        """engine is an AsyncEngine at module level."""
        from core.db.engine import engine

        assert isinstance(engine, AsyncEngine)

    def test_async_session_factory_exists(self):
        """async_session_factory is callable."""
        from core.db.engine import async_session_factory

        assert callable(async_session_factory)


class TestGetSession:
    """get_session() FastAPI dependency."""

    async def test_yields_session(self):
        """get_session yields an AsyncSession."""
        from sqlalchemy.ext.asyncio import AsyncSession

        from core.db.engine import get_session

        gen = get_session()
        session = await gen.__anext__()
        assert isinstance(session, AsyncSession)
        # Clean up
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass


class TestInitDb:
    """init_db() creates tables and enables WAL for SQLite."""

    async def test_init_db_creates_tables(self):
        """init_db() runs without error using in-memory SQLite."""
        from sqlalchemy.ext.asyncio import create_async_engine

        from core.db.models import register_all_models

        register_all_models()

        test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)

        with patch("core.db.engine.engine", test_engine):
            from core.db.engine import init_db

            await init_db()

        # Verify tables were created
        async with test_engine.begin() as conn:
            from sqlalchemy import inspect

            def check_tables(sync_conn):
                inspector = inspect(sync_conn)
                return inspector.get_table_names()

            tables = await conn.run_sync(check_tables)
            assert "users" in tables
            assert "sessions" in tables
            assert "memories" in tables

        await test_engine.dispose()

    async def test_init_db_skips_create_all_outside_dev(self):
        from contextlib import asynccontextmanager

        from core.db.engine import init_db

        class FakeConn:
            def __init__(self):
                self.run_sync_called = False

            async def execute(self, *_args, **_kwargs):
                return None

            async def run_sync(self, _fn):
                self.run_sync_called = True

        fake_conn = FakeConn()

        class FakeEngine:
            url = "sqlite+aiosqlite://"

            @asynccontextmanager
            async def begin(self):
                yield fake_conn

        fake_engine = FakeEngine()

        with patch.dict(
            os.environ, {"OPEN_AGENT_DEV": "0", "OPEN_AGENT_BOOTSTRAP_SCHEMA": "0"}, clear=False
        ):
            with patch("core.db.engine.engine", fake_engine):
                await init_db()

        assert fake_conn.run_sync_called is False


class TestCloseDb:
    """close_db() disposes engine."""

    async def test_close_db(self):
        """close_db() calls engine.dispose()."""
        from sqlalchemy.ext.asyncio import create_async_engine

        test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
        with patch("core.db.engine.engine", test_engine):
            from core.db.engine import close_db

            await close_db()


class TestRegisterAllModels:
    """register_all_models() in core.db.models.__init__."""

    def test_register_all_models(self):
        """register_all_models() runs without error."""
        from core.db.models import register_all_models

        register_all_models()

    def test_all_models_importable(self):
        """All ORM models are importable from core.db.models."""
        from core.db.models import (
            APIKeyORM,
            JobORM,
            JobRunRecordORM,
            MCPConfigORM,
            MemoryORM,
            PageORM,
            RefreshTokenORM,
            SessionMessageORM,
            SessionORM,
            SessionSummaryORM,
            SettingsORM,
            SkillConfigORM,
            UserORM,
            WorkspaceORM,
        )

        assert UserORM.__tablename__ == "users"
        assert SessionORM.__tablename__ == "sessions"
        assert MemoryORM.__tablename__ == "memories"
        assert JobORM.__tablename__ == "jobs"
        assert PageORM.__tablename__ == "pages"
        assert SettingsORM.__tablename__ == "settings"
        assert MCPConfigORM.__tablename__ == "mcp_configs"
        assert SkillConfigORM.__tablename__ == "skill_configs"
        assert WorkspaceORM.__tablename__ == "workspaces"
        assert APIKeyORM.__tablename__ == "api_keys"
        assert RefreshTokenORM.__tablename__ == "refresh_tokens"
        assert SessionMessageORM.__tablename__ == "session_messages"
        assert SessionSummaryORM.__tablename__ == "session_summaries"
        assert JobRunRecordORM.__tablename__ == "job_run_records"


class TestBase:
    """core.db.base module."""

    def test_base_is_declarative(self):
        """Base is a DeclarativeBase."""
        from sqlalchemy.orm import DeclarativeBase

        from core.db.base import Base

        assert issubclass(Base, DeclarativeBase)

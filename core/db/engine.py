"""Async database engine and session factory.

Default: SQLite at ~/.open-agent/open_agent.db
Override: Set DATABASE_URL environment variable for PostgreSQL, etc.
"""

import os
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _build_database_url() -> str:
    """Resolve database URL from environment or default to SQLite."""
    url = os.getenv("DATABASE_URL")
    if url:
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    from open_agent.config import get_data_dir

    db_path = get_data_dir() / "open_agent.db"
    return f"sqlite+aiosqlite:///{db_path}"


def _create_engine() -> AsyncEngine:
    """Build the async engine with backend-appropriate settings."""
    url = _build_database_url()
    is_sqlite = url.startswith("sqlite")

    connect_args: dict = {}
    pool_kwargs: dict = {}

    if is_sqlite:
        connect_args["check_same_thread"] = False
        pool_kwargs["pool_size"] = 1
        pool_kwargs["max_overflow"] = 0
    else:
        pool_kwargs["pool_size"] = 5
        pool_kwargs["max_overflow"] = 10

    return create_async_engine(
        url,
        connect_args=connect_args,
        echo=os.getenv("OPEN_AGENT_DB_ECHO", "") == "1",
        **pool_kwargs,
    )


engine: AsyncEngine = _create_engine()
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield an async DB session."""
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """Initialize database: create tables, enable WAL for SQLite."""
    from core.db.base import Base
    from core.db.models import register_all_models  # noqa: F401 — ensure models are loaded

    bootstrap_schema = (
        os.getenv("OPEN_AGENT_DEV", "") == "1"
        or os.getenv("OPEN_AGENT_BOOTSTRAP_SCHEMA", "") == "1"
    )

    async with engine.begin() as conn:
        if str(engine.url).startswith("sqlite"):
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA busy_timeout=5000"))
        if bootstrap_schema:
            await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose engine on shutdown."""
    await engine.dispose()

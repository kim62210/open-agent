"""Global test fixtures — isolated in-memory DB + singleton manager init."""

# -- open_agent package mapping --
# hatchling packages=["."] maps the project root as the open_agent package at build time.
# In editable installs the directory name (local-agent) may differ from the package name
# (open_agent), so we register the mapping in sys.modules before any test imports.
import importlib
import sys
from pathlib import Path as _Path

_PROJECT_ROOT = _Path(__file__).resolve().parent.parent

if "open_agent" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "open_agent",
        _PROJECT_ROOT / "__init__.py",
        submodule_search_locations=[str(_PROJECT_ROOT)],
    )
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules["open_agent"] = _mod
        _spec.loader.exec_module(_mod)

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.db.base import Base

logger = logging.getLogger(__name__)

# -- Default settings template (for SettingsManager tests) --

_DEFAULT_SETTINGS = {
    "llm": {
        "model": "gemini/gemini-2.0-flash",
        "temperature": 0.7,
        "max_tokens": 16384,
        "system_prompt": "",
    },
    "memory": {
        "enabled": True,
        "max_memories": 50,
        "max_injection_tokens": 2000,
        "compression_threshold": 0.8,
        "extraction_interval": 3,
    },
    "profile": {
        "name": "",
        "avatar": "",
        "platform_name": "Open Agent",
        "platform_subtitle": "Open Agent System",
        "bot_name": "Open Agent Core",
        "bot_avatar": "",
    },
    "theme": {
        "accent_color": "amber",
        "mode": "dark",
        "tone": "default",
        "show_blobs": True,
        "chat_bg_image": "",
        "chat_bg_opacity": 0.3,
        "chat_bg_scale": 1.1,
        "chat_bg_position_x": 50,
        "chat_bg_position_y": 50,
        "font_scale": 1.0,
    },
}

# -- Database fixtures --


@pytest.fixture()
async def db_engine():
    """In-memory SQLite engine for testing. Tables created, then disposed."""
    # Import all models so Base.metadata knows every table
    from core.db.models import register_all_models
    register_all_models()

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def db_session(db_engine):
    """Async session bound to the in-memory test engine."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture()
async def test_user(db_engine):
    """Create a test user and return user dict."""
    from core.auth.password import hash_password
    from core.db.models.user import UserORM

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        user = UserORM(
            id="test-user-id",
            email="test@example.com",
            username="testuser",
            password_hash=hash_password("testpass123"),
            role="user",
            is_active=True,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        session.add(user)
        await session.commit()
    return {"id": "test-user-id", "email": "test@example.com", "username": "testuser", "role": "user"}


@pytest.fixture()
async def auth_headers(test_user):
    """JWT auth headers for test requests."""
    from core.auth.jwt import create_access_token

    token = create_access_token({"sub": test_user["id"], "role": test_user["role"]})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
async def _patch_db_factory(db_engine, monkeypatch):
    """Patch async_session_factory everywhere managers import it."""
    import importlib
    import core.db.engine  # ensure the module is loaded

    _engine_mod = sys.modules["core.db.engine"]
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(_engine_mod, "async_session_factory", factory)

    # Also patch any module that copied the reference at import time
    if "core.auth.dependencies" in sys.modules:
        monkeypatch.setattr(sys.modules["core.auth.dependencies"], "async_session_factory", factory)


# -- Manager fixtures --


@pytest.fixture()
async def session_manager(_patch_db_factory):
    """Isolated SessionManager backed by in-memory DB."""
    from open_agent.core.session_manager import SessionManager

    mgr = SessionManager()
    return mgr


@pytest.fixture()
async def memory_manager(_patch_db_factory):
    """Isolated MemoryManager backed by in-memory DB."""
    from open_agent.core.memory_manager import MemoryManager

    mgr = MemoryManager()
    return mgr


@pytest.fixture()
async def settings_manager(_patch_db_factory):
    """Isolated SettingsManager backed by in-memory DB."""
    from open_agent.core.settings_manager import SettingsManager

    mgr = SettingsManager()
    return mgr


@pytest.fixture()
def mock_llm(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Mock LLM calls so tests run without real API calls.

    Patches llm_client.simple_completion (used by memory_manager) and
    litellm.acompletion (used by llm.py internals) to return safe defaults.
    """
    # Mock simple_completion (used by memory_manager via llm_client)
    simple_mock = AsyncMock(return_value="mocked response")
    monkeypatch.setattr(
        "open_agent.core.llm.LLMClient.simple_completion", simple_mock,
    )

    # Also mock acompletion at the llm module level for chat_completion/classify
    mock_message = MagicMock()
    mock_message.content = "mocked response"
    mock_message.reasoning_content = None

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.model_dump = MagicMock(return_value={
        "choices": [{"message": {"content": "mocked response", "tool_calls": None}}],
    })

    acompletion_mock = AsyncMock(return_value=mock_response)
    monkeypatch.setattr("open_agent.core.llm.acompletion", acompletion_mock)

    return simple_mock


@pytest.fixture()
async def async_client(_patch_db_factory, monkeypatch: pytest.MonkeyPatch):
    """httpx.AsyncClient + ASGITransport for FastAPI integration tests.

    Singleton managers are patched to use the in-memory test DB.
    Auth dependencies are overridden to return a fake user so session
    endpoints that require authentication work without a real JWT.
    """
    import httpx
    from httpx import ASGITransport

    from open_agent.core.memory_manager import memory_manager as _mm
    from open_agent.core.session_manager import session_manager as _sm
    from open_agent.core.settings_manager import settings_manager as _stm

    # Backup original state
    orig_sm_sessions = _sm._sessions.copy()
    orig_mm_memories = _mm._memories.copy()
    orig_stm_settings = _stm._settings

    # Reset singleton state for isolation
    _sm._sessions.clear()
    _mm._memories.clear()

    # Initialize settings from defaults (DB-backed but via in-memory SQLite)
    from open_agent.models.settings import AppSettings
    _stm._settings = AppSettings(**_DEFAULT_SETTINGS)

    # Lightweight app without lifespan — only register the sessions router
    from fastapi import FastAPI
    from open_agent.api.endpoints import sessions as sessions_router

    test_app = FastAPI()
    test_app.include_router(sessions_router.router, prefix="/api/sessions")

    # Override auth dependency so session tests don't need a real JWT
    from core.auth.dependencies import get_current_user

    async def _fake_current_user() -> dict:
        return {"id": "test-user-id", "email": "test@example.com", "username": "testuser", "role": "admin"}

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # Restore singleton state
    _sm._sessions = orig_sm_sessions
    _mm._memories = orig_mm_memories
    _stm._settings = orig_stm_settings


@pytest.fixture()
async def auth_client(_patch_db_factory):
    """httpx.AsyncClient wired to auth + session routers with real auth dependencies.

    Uses the patched in-memory DB so JWT validation lookups hit the test DB.
    Rate limiting is disabled to avoid 429 errors across test isolation boundaries.
    """
    import httpx
    from httpx import ASGITransport

    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from core.auth.rate_limit import limiter
    from open_agent.api.endpoints import auth as auth_router
    from open_agent.api.endpoints import sessions as sessions_router

    # Disable rate limiting for tests
    limiter.enabled = False

    test_app = FastAPI()
    test_app.state.limiter = limiter
    test_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    test_app.include_router(auth_router.router, prefix="/api/auth")
    test_app.include_router(sessions_router.router, prefix="/api/sessions")

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # Re-enable rate limiting after tests
    limiter.enabled = True

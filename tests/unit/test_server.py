"""Server tests — exception handlers, CORS, basic routing."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.fixture()
async def server_client():
    """httpx.AsyncClient using the real app but with mocked lifespan."""
    import httpx
    from httpx import ASGITransport

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from core.auth.dependencies import get_current_user
    from open_agent.server import _register_exception_handlers
    from open_agent.core.exceptions import (
        AlreadyExistsError,
        InvalidPathError,
        JobStateError,
        LLMContextWindowError,
        LLMError,
        LLMRateLimitError,
        MCPConnectionError,
        NotFoundError,
        NotInitializedError,
        OpenAgentError,
        PermissionDeniedError,
        StorageLimitError,
    )

    test_app = FastAPI()
    _register_exception_handlers(test_app)

    async def _fake_current_user() -> dict:
        return {"id": "test-user-id", "email": "test@example.com", "username": "testuser", "role": "admin"}

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    # Register test routes that raise each exception type
    @test_app.get("/test/not-found")
    async def _raise_not_found():
        raise NotFoundError("Resource not found")

    @test_app.get("/test/already-exists")
    async def _raise_already_exists():
        raise AlreadyExistsError("Already exists")

    @test_app.get("/test/permission-denied")
    async def _raise_permission_denied():
        raise PermissionDeniedError("Forbidden")

    @test_app.get("/test/invalid-path")
    async def _raise_invalid_path():
        raise InvalidPathError("Bad path")

    @test_app.get("/test/storage-limit")
    async def _raise_storage_limit():
        raise StorageLimitError("Too large")

    @test_app.get("/test/job-state")
    async def _raise_job_state():
        raise JobStateError("Invalid state")

    @test_app.get("/test/llm-rate-limit")
    async def _raise_llm_rate_limit():
        raise LLMRateLimitError("Rate limited")

    @test_app.get("/test/llm-context-window")
    async def _raise_llm_context():
        raise LLMContextWindowError("Context too large")

    @test_app.get("/test/llm-error")
    async def _raise_llm_error():
        raise LLMError("LLM failed")

    @test_app.get("/test/mcp-connection")
    async def _raise_mcp_connection():
        raise MCPConnectionError("MCP failed")

    @test_app.get("/test/not-initialized")
    async def _raise_not_initialized():
        raise NotInitializedError("Not initialized")

    @test_app.get("/test/open-agent-error")
    async def _raise_open_agent():
        raise OpenAgentError("Generic error")

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestNotFoundHandler:
    """NotFoundError -> 404"""

    async def test_not_found(self, server_client: AsyncClient):
        resp = await server_client.get("/test/not-found")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


class TestAlreadyExistsHandler:
    """AlreadyExistsError -> 409"""

    async def test_already_exists(self, server_client: AsyncClient):
        resp = await server_client.get("/test/already-exists")
        assert resp.status_code == 409


class TestPermissionDeniedHandler:
    """PermissionDeniedError -> 403"""

    async def test_permission_denied(self, server_client: AsyncClient):
        resp = await server_client.get("/test/permission-denied")
        assert resp.status_code == 403


class TestInvalidPathHandler:
    """InvalidPathError -> 400"""

    async def test_invalid_path(self, server_client: AsyncClient):
        resp = await server_client.get("/test/invalid-path")
        assert resp.status_code == 400


class TestStorageLimitHandler:
    """StorageLimitError -> 413"""

    async def test_storage_limit(self, server_client: AsyncClient):
        resp = await server_client.get("/test/storage-limit")
        assert resp.status_code == 413


class TestJobStateHandler:
    """JobStateError -> 409"""

    async def test_job_state(self, server_client: AsyncClient):
        resp = await server_client.get("/test/job-state")
        assert resp.status_code == 409


class TestLLMRateLimitHandler:
    """LLMRateLimitError -> 429"""

    async def test_llm_rate_limit(self, server_client: AsyncClient):
        resp = await server_client.get("/test/llm-rate-limit")
        assert resp.status_code == 429


class TestLLMContextWindowHandler:
    """LLMContextWindowError -> 400"""

    async def test_llm_context_window(self, server_client: AsyncClient):
        resp = await server_client.get("/test/llm-context-window")
        assert resp.status_code == 400


class TestLLMErrorHandler:
    """LLMError -> 502"""

    async def test_llm_error(self, server_client: AsyncClient):
        resp = await server_client.get("/test/llm-error")
        assert resp.status_code == 502


class TestMCPConnectionHandler:
    """MCPConnectionError -> 502"""

    async def test_mcp_connection(self, server_client: AsyncClient):
        resp = await server_client.get("/test/mcp-connection")
        assert resp.status_code == 502


class TestNotInitializedHandler:
    """NotInitializedError -> 500"""

    async def test_not_initialized(self, server_client: AsyncClient):
        resp = await server_client.get("/test/not-initialized")
        assert resp.status_code == 500


class TestOpenAgentFallbackHandler:
    """OpenAgentError (fallback) -> 500"""

    async def test_open_agent_fallback(self, server_client: AsyncClient):
        resp = await server_client.get("/test/open-agent-error")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"

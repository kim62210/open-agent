"""Chat API integration tests — POST /api/chat and POST /api/chat/stream."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.fixture()
async def chat_client(_patch_db_factory, monkeypatch):
    """httpx.AsyncClient wired to chat router with mocked orchestrator.

    core/agent.py has a pre-existing syntax error (await in sync func),
    so we pre-inject a mock orchestrator into sys.modules before importing chat.
    """
    import importlib
    import httpx
    from httpx import ASGITransport

    from fastapi import FastAPI
    from core.auth.dependencies import get_current_user

    # Pre-inject a mock for core.agent so chat.py can import orchestrator
    mock_agent_mod = MagicMock()
    mock_agent_mod.orchestrator = MagicMock()
    already_loaded = "open_agent.core.agent" in sys.modules
    if not already_loaded:
        sys.modules["open_agent.core.agent"] = mock_agent_mod

    # Now safe to import chat module
    from open_agent.api.endpoints import chat

    test_app = FastAPI()
    test_app.include_router(chat.router, prefix="/api/chat")

    async def _fake_current_user() -> dict:
        return {"id": "test-user-id", "email": "test@example.com", "username": "testuser", "role": "admin"}

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    if not already_loaded:
        sys.modules.pop("open_agent.core.agent", None)


class TestChatEndpoint:
    """POST /api/chat"""

    async def test_chat_returns_response(self, chat_client: AsyncClient):
        """Successful chat returns orchestrator response."""
        mock_response = {"choices": [{"message": {"content": "Hello!"}}]}
        with patch("open_agent.api.endpoints.chat.orchestrator") as mock_orch:
            mock_orch.run = AsyncMock(return_value=mock_response)
            resp = await chat_client.post(
                "/api/chat/",
                json={"messages": [{"role": "user", "content": "Hi"}]},
            )
        assert resp.status_code == 200
        assert resp.json() == mock_response

    async def test_chat_with_forced_workflow(self, chat_client: AsyncClient):
        """Chat with forced_workflow passes it to orchestrator."""
        mock_response = {"choices": [{"message": {"content": "Done"}}]}
        with patch("open_agent.api.endpoints.chat.orchestrator") as mock_orch:
            mock_orch.run = AsyncMock(return_value=mock_response)
            resp = await chat_client.post(
                "/api/chat/",
                json={
                    "messages": [{"role": "user", "content": "Do something"}],
                    "forced_workflow": "coder",
                },
            )
        assert resp.status_code == 200
        mock_orch.run.assert_called_once_with(
            [{"role": "user", "content": "Do something"}],
            forced_workflow="coder",
        )

    async def test_chat_invalid_role_returns_422(self, chat_client: AsyncClient):
        """Messages with invalid role are rejected by Pydantic validator."""
        resp = await chat_client.post(
            "/api/chat/",
            json={"messages": [{"role": "system", "content": "Bad role"}]},
        )
        assert resp.status_code == 422

    async def test_chat_empty_messages(self, chat_client: AsyncClient):
        """Empty messages list is allowed (orchestrator decides what to do)."""
        mock_response = {"choices": []}
        with patch("open_agent.api.endpoints.chat.orchestrator") as mock_orch:
            mock_orch.run = AsyncMock(return_value=mock_response)
            resp = await chat_client.post(
                "/api/chat/",
                json={"messages": []},
            )
        assert resp.status_code == 200

    async def test_chat_orchestrator_error_returns_500(self, chat_client: AsyncClient):
        """When orchestrator raises, endpoint returns 500."""
        with patch("open_agent.api.endpoints.chat.orchestrator") as mock_orch:
            mock_orch.run = AsyncMock(side_effect=RuntimeError("LLM failed"))
            resp = await chat_client.post(
                "/api/chat/",
                json={"messages": [{"role": "user", "content": "Hi"}]},
            )
        assert resp.status_code == 500
        assert "LLM failed" in resp.json()["detail"]

    async def test_chat_tool_role_allowed(self, chat_client: AsyncClient):
        """Tool role is in the allowed set."""
        mock_response = {"choices": [{"message": {"content": "ok"}}]}
        with patch("open_agent.api.endpoints.chat.orchestrator") as mock_orch:
            mock_orch.run = AsyncMock(return_value=mock_response)
            resp = await chat_client.post(
                "/api/chat/",
                json={"messages": [{"role": "tool", "content": "result"}]},
            )
        assert resp.status_code == 200


class TestChatStreamEndpoint:
    """POST /api/chat/stream"""

    async def test_stream_returns_sse(self, chat_client: AsyncClient):
        """Streaming endpoint returns text/event-stream content type."""
        async def fake_stream(*args, **kwargs):
            yield {"type": "token", "content": "Hello"}
            yield {"type": "done", "full_response": {"choices": [{"message": {"content": "Hello"}}]}}

        with patch("open_agent.api.endpoints.chat.orchestrator") as mock_orch:
            mock_orch.run_stream = fake_stream
            resp = await chat_client.post(
                "/api/chat/stream",
                json={"messages": [{"role": "user", "content": "Hi"}]},
            )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    async def test_stream_contains_events(self, chat_client: AsyncClient):
        """Stream response contains SSE-formatted data lines."""
        async def fake_stream(*args, **kwargs):
            yield {"type": "token", "content": "Hi"}
            yield {"type": "done", "full_response": {}}

        with patch("open_agent.api.endpoints.chat.orchestrator") as mock_orch:
            mock_orch.run_stream = fake_stream
            resp = await chat_client.post(
                "/api/chat/stream",
                json={"messages": [{"role": "user", "content": "Hello"}]},
            )
        body = resp.text
        assert "data:" in body

    async def test_stream_error_yields_error_event(self, chat_client: AsyncClient):
        """When stream generator raises, an error event is yielded."""
        async def failing_stream(*args, **kwargs):
            raise RuntimeError("Stream broke")
            yield  # make it a generator

        with patch("open_agent.api.endpoints.chat.orchestrator") as mock_orch:
            mock_orch.run_stream = failing_stream
            resp = await chat_client.post(
                "/api/chat/stream",
                json={"messages": [{"role": "user", "content": "Hi"}]},
            )
        assert resp.status_code == 200
        assert "error" in resp.text


class TestChatHelpers:
    """Test helper functions in the chat module."""

    def test_extract_text_string(self):
        """_extract_text handles plain string content."""
        from open_agent.api.endpoints.chat import _extract_text
        assert _extract_text("hello") == "hello"

    def test_extract_text_multimodal(self):
        """_extract_text handles multimodal array content."""
        from open_agent.api.endpoints.chat import _extract_text
        content = [{"type": "text", "text": "hello"}, {"type": "image", "url": "http://x"}]
        assert _extract_text(content) == "hello"

    def test_extract_text_empty_list(self):
        """_extract_text returns empty string for no text parts."""
        from open_agent.api.endpoints.chat import _extract_text
        assert _extract_text([{"type": "image", "url": "http://x"}]) == ""

    def test_safe_get_content_normal(self):
        """_safe_get_content extracts assistant content from response dict."""
        from open_agent.api.endpoints.chat import _safe_get_content
        resp = {"choices": [{"message": {"content": "Hi there"}}]}
        assert _safe_get_content(resp) == "Hi there"

    def test_safe_get_content_none(self):
        """_safe_get_content returns empty string for None content."""
        from open_agent.api.endpoints.chat import _safe_get_content
        resp = {"choices": [{"message": {"content": None}}]}
        assert _safe_get_content(resp) == ""

    def test_safe_get_content_empty_response(self):
        """_safe_get_content handles empty dict gracefully."""
        from open_agent.api.endpoints.chat import _safe_get_content
        assert _safe_get_content({}) == ""

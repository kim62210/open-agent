"""Memory API integration tests — listing, create, update, delete."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from open_agent.models.memory import MemoryItem


@pytest.fixture()
async def memory_client(_patch_db_factory, monkeypatch):
    """httpx.AsyncClient wired to memory router with mocked memory_manager."""
    import httpx
    from httpx import ASGITransport

    from fastapi import FastAPI
    from core.auth.dependencies import get_current_user
    from open_agent.api.endpoints import memory as memory_router

    test_app = FastAPI()
    test_app.include_router(memory_router.router, prefix="/api/memory")

    async def _fake_current_user() -> dict:
        return {"id": "test-user-id", "email": "test@example.com", "username": "testuser", "role": "admin"}

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _make_memory_item(id="mem-1", content="Test memory", is_pinned=False):
    return MemoryItem(
        id=id, content=content, category="fact", confidence=0.7,
        source="llm_inference", is_pinned=is_pinned,
        created_at="2024-01-01T00:00:00Z", updated_at="2024-01-01T00:00:00Z",
    )


class TestListMemories:
    """GET /api/memory/"""

    async def test_list_empty(self, memory_client: AsyncClient):
        """Returns empty list when no memories exist."""
        with patch("open_agent.api.endpoints.memory.memory_manager") as mock_mm:
            mock_mm.get_all.return_value = []
            resp = await memory_client.get("/api/memory/")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_returns_memories(self, memory_client: AsyncClient):
        """Returns list of memories."""
        with patch("open_agent.api.endpoints.memory.memory_manager") as mock_mm:
            mock_mm.get_all.return_value = [_make_memory_item()]
            resp = await memory_client.get("/api/memory/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestCreateMemory:
    """POST /api/memory/"""

    async def test_create_memory(self, memory_client: AsyncClient):
        """Creates a new memory."""
        mem = _make_memory_item()
        with patch("open_agent.api.endpoints.memory.memory_manager") as mock_mm:
            mock_mm.create = AsyncMock(return_value=mem)
            resp = await memory_client.post(
                "/api/memory/",
                json={"content": "New fact", "category": "fact"},
            )
        assert resp.status_code == 201


class TestUpdateMemory:
    """PATCH /api/memory/{memory_id}"""

    async def test_update_memory(self, memory_client: AsyncClient):
        """Updates a memory."""
        mem = _make_memory_item(content="Updated")
        with patch("open_agent.api.endpoints.memory.memory_manager") as mock_mm:
            mock_mm.update = AsyncMock(return_value=mem)
            resp = await memory_client.patch(
                "/api/memory/mem-1", json={"content": "Updated"}
            )
        assert resp.status_code == 200

    async def test_update_nonexistent_memory(self, memory_client: AsyncClient):
        """Returns 404 for non-existent memory."""
        with patch("open_agent.api.endpoints.memory.memory_manager") as mock_mm:
            mock_mm.update = AsyncMock(return_value=None)
            resp = await memory_client.patch(
                "/api/memory/nonexistent", json={"content": "Nope"}
            )
        assert resp.status_code == 404


class TestTogglePin:
    """PATCH /api/memory/{memory_id}/pin"""

    async def test_toggle_pin(self, memory_client: AsyncClient):
        """Toggles pin state."""
        mem = _make_memory_item(is_pinned=False)
        pinned = _make_memory_item(is_pinned=True)
        with patch("open_agent.api.endpoints.memory.memory_manager") as mock_mm:
            mock_mm.get.return_value = mem
            mock_mm.update = AsyncMock(return_value=pinned)
            resp = await memory_client.patch("/api/memory/mem-1/pin")
        assert resp.status_code == 200

    async def test_toggle_pin_nonexistent(self, memory_client: AsyncClient):
        """Returns 404 for non-existent memory."""
        with patch("open_agent.api.endpoints.memory.memory_manager") as mock_mm:
            mock_mm.get.return_value = None
            resp = await memory_client.patch("/api/memory/nonexistent/pin")
        assert resp.status_code == 404


class TestDeleteMemory:
    """DELETE /api/memory/{memory_id}"""

    async def test_delete_memory(self, memory_client: AsyncClient):
        """Deletes a memory."""
        with patch("open_agent.api.endpoints.memory.memory_manager") as mock_mm:
            mock_mm.delete = AsyncMock(return_value=True)
            resp = await memory_client.delete("/api/memory/mem-1")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_delete_nonexistent_memory(self, memory_client: AsyncClient):
        """Returns 404 for non-existent memory."""
        with patch("open_agent.api.endpoints.memory.memory_manager") as mock_mm:
            mock_mm.delete = AsyncMock(return_value=False)
            resp = await memory_client.delete("/api/memory/nonexistent")
        assert resp.status_code == 404


class TestClearAllMemories:
    """DELETE /api/memory/"""

    async def test_clear_all(self, memory_client: AsyncClient):
        """Clears all memories."""
        with patch("open_agent.api.endpoints.memory.memory_manager") as mock_mm:
            mock_mm.clear_all = AsyncMock(return_value=5)
            resp = await memory_client.delete("/api/memory/")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 5

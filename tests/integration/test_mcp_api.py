"""MCP API integration tests — config CRUD, server control."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from open_agent.models.mcp import MCPServerConfig, MCPServerInfo


@pytest.fixture()
async def mcp_client(_patch_db_factory, monkeypatch):
    """httpx.AsyncClient wired to MCP router with mocked mcp_manager."""
    import httpx
    from fastapi import FastAPI
    from httpx import ASGITransport
    from open_agent.api.endpoints import mcp as mcp_router

    from core.auth.dependencies import get_current_user

    test_app = FastAPI()
    test_app.include_router(mcp_router.router, prefix="/api/mcp")

    async def _fake_current_user() -> dict:
        return {
            "id": "test-user-id",
            "email": "test@example.com",
            "username": "testuser",
            "role": "admin",
        }

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture()
async def non_admin_mcp_client(_patch_db_factory):
    import httpx
    from fastapi import FastAPI
    from httpx import ASGITransport
    from open_agent.api.endpoints import mcp as mcp_router

    from core.auth.dependencies import get_current_user

    test_app = FastAPI()
    test_app.include_router(mcp_router.router, prefix="/api/mcp")

    async def _fake_current_user() -> dict:
        return {
            "id": "test-user-id",
            "email": "user@example.com",
            "username": "regularuser",
            "role": "user",
        }

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _make_server_info(name="test-server", status="disconnected"):
    return MCPServerInfo(
        name=name,
        config=MCPServerConfig(transport="stdio", command="echo", enabled=True),
        status=status,
    )


class TestGetConfig:
    """GET /api/mcp/config"""

    async def test_get_config(self, mcp_client: AsyncClient):
        """Returns raw MCP config."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm.get_raw_config.return_value = {"mcpServers": {}}
            resp = await mcp_client.get("/api/mcp/config")
        assert resp.status_code == 200
        assert "mcpServers" in resp.json()


class TestListServers:
    """GET /api/mcp/servers"""

    async def test_list_servers_empty(self, mcp_client: AsyncClient):
        """Returns empty list when no servers configured."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm.get_all_server_statuses.return_value = []
            resp = await mcp_client.get("/api/mcp/servers")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_servers_with_tools(self, mcp_client: AsyncClient):
        """Returns server info with tools for connected servers."""
        info = _make_server_info(status="connected")
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm.get_all_server_statuses.return_value = [info]
            mock_mm.get_tools_for_server = AsyncMock(return_value=[])
            resp = await mcp_client.get("/api/mcp/servers")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestGetServer:
    """GET /api/mcp/servers/{name}"""

    async def test_get_server_found(self, mcp_client: AsyncClient):
        """Returns server info by name."""
        info = _make_server_info()
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm.get_server_status.return_value = info
            resp = await mcp_client.get("/api/mcp/servers/test-server")
        assert resp.status_code == 200

    async def test_get_server_not_found(self, mcp_client: AsyncClient):
        """Returns 404 for non-existent server."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm.get_server_status.side_effect = ValueError("not found")
            resp = await mcp_client.get("/api/mcp/servers/nonexistent")
        assert resp.status_code == 404

    async def test_get_server_redacts_sensitive_config_fields(self, mcp_client: AsyncClient):
        info = MCPServerInfo(
            name="secure-server",
            config=MCPServerConfig(
                transport="streamable-http",
                url="https://example.com/mcp",
                env={"OPENAI_API_KEY": "super-secret-token"},
                headers={"Authorization": "Bearer top-secret-value", "X-Trace": "safe"},
                enabled=True,
            ),
            status="connected",
        )
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm.get_server_status.return_value = info
            mock_mm.get_tools_for_server = AsyncMock(return_value=[])
            resp = await mcp_client.get("/api/mcp/servers/secure-server")

        assert resp.status_code == 200
        data = resp.json()
        assert data["config"]["env"] == {"OPENAI_API_KEY": "***"}
        assert data["config"]["headers"]["Authorization"] != "Bearer top-secret-value"
        assert data["config"]["headers"]["X-Trace"] == "safe"


class TestAddServer:
    """POST /api/mcp/servers"""

    async def test_add_server(self, mcp_client: AsyncClient):
        """Adds a new MCP server."""
        info = _make_server_info()
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {}
            mock_mm.add_server_config = AsyncMock()
            mock_mm.connect_server = AsyncMock()
            mock_mm.get_server_status.return_value = info
            resp = await mcp_client.post(
                "/api/mcp/servers",
                json={
                    "name": "test-server",
                    "config": {"transport": "stdio", "command": "echo", "enabled": True},
                },
            )
        assert resp.status_code == 200

    async def test_add_duplicate_server(self, mcp_client: AsyncClient):
        """Returns 409 for duplicate server name."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {"test-server": MagicMock()}
            resp = await mcp_client.post(
                "/api/mcp/servers",
                json={
                    "name": "test-server",
                    "config": {"transport": "stdio", "command": "echo"},
                },
            )
        assert resp.status_code == 409


class TestDeleteServer:
    """DELETE /api/mcp/servers/{name}"""

    async def test_delete_server(self, mcp_client: AsyncClient):
        """Deletes an MCP server."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {"test-server": MagicMock()}
            mock_mm.disconnect_server = AsyncMock()
            mock_mm.remove_server_config = AsyncMock()
            resp = await mcp_client.delete("/api/mcp/servers/test-server")
        assert resp.status_code == 200

    async def test_delete_nonexistent_server(self, mcp_client: AsyncClient):
        """Returns 404 for non-existent server."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {}
            resp = await mcp_client.delete("/api/mcp/servers/nonexistent")
        assert resp.status_code == 404


class TestConnectDisconnect:
    """Server connection control endpoints."""

    async def test_connect_server(self, mcp_client: AsyncClient):
        """POST /api/mcp/servers/{name}/connect"""
        info = _make_server_info(status="connected")
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {"test-server": MagicMock()}
            mock_mm.connect_server = AsyncMock()
            mock_mm.get_server_status.return_value = info
            mock_mm.get_tools_for_server = AsyncMock(return_value=[])
            resp = await mcp_client.post("/api/mcp/servers/test-server/connect")
        assert resp.status_code == 200

    async def test_disconnect_server(self, mcp_client: AsyncClient):
        """POST /api/mcp/servers/{name}/disconnect"""
        info = _make_server_info(status="disconnected")
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {"test-server": MagicMock()}
            mock_mm.disconnect_server = AsyncMock()
            mock_mm.get_server_status.return_value = info
            resp = await mcp_client.post("/api/mcp/servers/test-server/disconnect")
        assert resp.status_code == 200

    async def test_restart_server(self, mcp_client: AsyncClient):
        """POST /api/mcp/servers/{name}/restart"""
        info = _make_server_info(status="connected")
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {"test-server": MagicMock()}
            mock_mm.disconnect_server = AsyncMock()
            mock_mm.connect_server = AsyncMock()
            mock_mm.get_server_status.return_value = info
            mock_mm.get_tools_for_server = AsyncMock(return_value=[])
            resp = await mcp_client.post("/api/mcp/servers/test-server/restart")
        assert resp.status_code == 200

    async def test_connect_nonexistent_returns_404(self, mcp_client: AsyncClient):
        """Connect to non-existent server returns 404."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {}
            resp = await mcp_client.post("/api/mcp/servers/nonexistent/connect")
        assert resp.status_code == 404


class TestListTools:
    """GET /api/mcp/tools"""

    async def test_list_all_tools(self, mcp_client: AsyncClient):
        """Returns tools from all connected servers."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._connections = {}
            resp = await mcp_client.get("/api/mcp/tools")
        assert resp.status_code == 200
        assert resp.json() == []


class TestReloadConfig:
    """POST /api/mcp/reload"""

    async def test_reload_config(self, mcp_client: AsyncClient):
        """Reloads MCP config."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm.reload_config = AsyncMock()
            mock_mm._configs = {"server-1": MagicMock()}
            resp = await mcp_client.post("/api/mcp/reload")
        assert resp.status_code == 200
        assert resp.json()["servers"] == 1


class TestUpdateServer:
    """PATCH /api/mcp/servers/{name}"""

    async def test_update_server(self, mcp_client: AsyncClient):
        """Updates server config."""
        info = _make_server_info()
        config_mock = MagicMock()
        config_mock.model_dump.return_value = {
            "transport": "stdio",
            "command": "echo",
            "enabled": True,
        }
        config_mock.enabled = True
        configs = {"test-server": config_mock}
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            type(mock_mm)._configs = property(lambda self: configs)
            mock_mm._connections = {}
            mock_mm.update_server_config = AsyncMock()
            mock_mm.connect_server = AsyncMock()
            mock_mm.get_server_status.return_value = info
            resp = await mcp_client.patch(
                "/api/mcp/servers/test-server",
                json={"command": "cat"},
            )
        assert resp.status_code == 200

    async def test_update_server_not_found(self, mcp_client: AsyncClient):
        """Returns 404 for non-existent server update."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            type(mock_mm)._configs = property(lambda self: {})
            resp = await mcp_client.patch(
                "/api/mcp/servers/nonexistent",
                json={"command": "cat"},
            )
        assert resp.status_code == 404

    async def test_update_server_disable(self, mcp_client: AsyncClient):
        """Disabling a server disconnects it."""
        info = _make_server_info(status="disconnected")
        config_mock = MagicMock()
        config_mock.model_dump.return_value = {
            "transport": "stdio",
            "command": "echo",
            "enabled": True,
        }
        disabled_config = MagicMock()
        disabled_config.enabled = False
        configs = {"test-server": config_mock}

        def _update_side_effect(name, updates):
            configs["test-server"] = disabled_config

        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            type(mock_mm)._configs = property(lambda self: configs)
            mock_mm._connections = {"test-server": MagicMock()}
            mock_mm.update_server_config = AsyncMock(side_effect=_update_side_effect)
            mock_mm.disconnect_server = AsyncMock()
            mock_mm.get_server_status.return_value = info
            resp = await mcp_client.patch(
                "/api/mcp/servers/test-server",
                json={"enabled": False},
            )
        assert resp.status_code == 200


class TestUpdateConfig:
    """PUT /api/mcp/config"""

    async def test_update_config(self, mcp_client: AsyncClient):
        """Overwrites full MCP config."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {}
            mock_mm.remove_server_config = AsyncMock()
            mock_mm.add_server_config = AsyncMock()
            mock_mm.reload_config = AsyncMock()
            mock_mm.get_raw_config.return_value = {
                "mcpServers": {"new-server": {"transport": "stdio", "command": "echo"}}
            }
            resp = await mcp_client.put(
                "/api/mcp/config",
                json={"mcpServers": {"new-server": {"transport": "stdio", "command": "echo"}}},
            )
        assert resp.status_code == 200
        assert "mcpServers" in resp.json()

    async def test_non_admin_cannot_update_config(self, non_admin_mcp_client: AsyncClient):
        resp = await non_admin_mcp_client.put(
            "/api/mcp/config",
            json={"mcpServers": {}},
        )
        assert resp.status_code == 403


class TestConnectDisconnectExtended:
    """Extended connection control tests."""

    async def test_disconnect_nonexistent_returns_404(self, mcp_client: AsyncClient):
        """Disconnect from non-existent server returns 404."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {}
            resp = await mcp_client.post("/api/mcp/servers/nonexistent/disconnect")
        assert resp.status_code == 404

    async def test_restart_nonexistent_returns_404(self, mcp_client: AsyncClient):
        """Restart non-existent server returns 404."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {}
            resp = await mcp_client.post("/api/mcp/servers/nonexistent/restart")
        assert resp.status_code == 404


class TestListServerTools:
    """GET /api/mcp/tools/{server_name}"""

    async def test_list_server_tools(self, mcp_client: AsyncClient):
        """Returns tools from a specific server."""
        from open_agent.models.mcp import MCPToolInfo

        tool = MCPToolInfo(
            name="read_file", description="Read a file", input_schema={}, server_name="test-server"
        )
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {"test-server": MagicMock()}
            mock_mm.get_tools_for_server = AsyncMock(return_value=[tool])
            resp = await mcp_client.get("/api/mcp/tools/test-server")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "read_file"

    async def test_list_server_tools_not_found(self, mcp_client: AsyncClient):
        """Returns 404 for non-existent server tools."""
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._configs = {}
            resp = await mcp_client.get("/api/mcp/tools/nonexistent")
        assert resp.status_code == 404


class TestListAllToolsExtended:
    """Extended tool listing tests."""

    async def test_list_all_tools_with_connections(self, mcp_client: AsyncClient):
        """Returns tools from all connected servers."""
        from open_agent.models.mcp import MCPToolInfo

        tool = MCPToolInfo(
            name="run_query", description="Run SQL query", input_schema={}, server_name="db-server"
        )
        with patch("open_agent.api.endpoints.mcp.mcp_manager") as mock_mm:
            mock_mm._connections = {"db-server": MagicMock()}
            mock_mm.get_tools_for_server = AsyncMock(return_value=[tool])
            resp = await mcp_client.get("/api/mcp/tools")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

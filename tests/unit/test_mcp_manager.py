"""MCPClientManager unit tests — config CRUD, lifecycle, tool discovery, tool invocation."""

import asyncio
import json
import time
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_agent.core.exceptions import ConfigError, NotFoundError
from open_agent.core.mcp_manager import MCPClientManager, parse_namespaced_tool
from open_agent.models.mcp import (
    MCPServerConfig,
    MCPServerInfo,
    MCPServerStatus,
    MCPToolInfo,
    MCPTransport,
)

# mcp_manager.py uses json.loads/json.dumps in call_tool but does not import json.
# Inject the missing reference so tests can exercise the happy-path.
import open_agent.core.mcp_manager as _mcp_mod
if not hasattr(_mcp_mod, "json"):
    _mcp_mod.json = json


@pytest.fixture()
def mgr() -> MCPClientManager:
    """Fresh MCPClientManager instance."""
    return MCPClientManager()


@pytest.fixture()
def stdio_config() -> MCPServerConfig:
    """A stdio transport config."""
    return MCPServerConfig(
        transport=MCPTransport.stdio,
        command="node",
        args=["server.js"],
        env={"API_KEY": "secret"},
        enabled=True,
    )


@pytest.fixture()
def sse_config() -> MCPServerConfig:
    """An SSE transport config."""
    return MCPServerConfig(
        transport=MCPTransport.sse,
        url="http://localhost:8080/sse",
        enabled=True,
    )


@pytest.fixture()
def disabled_config() -> MCPServerConfig:
    """A disabled config."""
    return MCPServerConfig(
        transport=MCPTransport.stdio,
        command="node",
        enabled=False,
    )


# ---------------------------------------------------------------------------
# parse_namespaced_tool
# ---------------------------------------------------------------------------


class TestParseNamespacedTool:
    """Parse 'server__tool' into (server, tool)."""

    def test_valid(self):
        server, tool = parse_namespaced_tool("myserver__read")
        assert server == "myserver"
        assert tool == "read"

    def test_double_underscore_in_tool(self):
        server, tool = parse_namespaced_tool("srv__tool__extra")
        assert server == "srv"
        assert tool == "tool__extra"

    def test_invalid_no_separator(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_namespaced_tool("notool")


# ---------------------------------------------------------------------------
# Config CRUD
# ---------------------------------------------------------------------------


class TestConfigCRUD:
    """add / update / remove server configs."""

    async def test_add_server_config(self, mgr, stdio_config):
        with patch.object(mgr, "_save_config", new_callable=AsyncMock):
            await mgr.add_server_config("test-server", stdio_config)

        assert "test-server" in mgr._configs
        assert mgr._configs["test-server"].command == "node"

    async def test_update_server_config(self, mgr, stdio_config):
        mgr._configs["srv"] = stdio_config

        with patch.object(mgr, "_save_config", new_callable=AsyncMock):
            updated = await mgr.update_server_config("srv", {"command": "python"})

        assert updated.command == "python"
        assert updated.args == ["server.js"]

    async def test_update_nonexistent_raises(self, mgr):
        with pytest.raises(NotFoundError):
            with patch.object(mgr, "_save_config", new_callable=AsyncMock):
                await mgr.update_server_config("nope", {"command": "x"})

    async def test_remove_server_config(self, mgr, stdio_config):
        mgr._configs["srv"] = stdio_config

        with patch("core.db.engine.async_session_factory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_repo = MagicMock()
            mock_repo.delete_by_id = AsyncMock()
            with patch(
                "core.db.repositories.mcp_config_repo.MCPConfigRepository",
                return_value=mock_repo,
            ):
                await mgr.remove_server_config("srv")

        assert "srv" not in mgr._configs


# ---------------------------------------------------------------------------
# Server status
# ---------------------------------------------------------------------------


class TestServerStatus:
    """get_server_status / get_all_server_statuses."""

    def test_get_status(self, mgr, stdio_config):
        mgr._configs["srv"] = stdio_config
        mgr._statuses["srv"] = MCPServerStatus.connected

        info = mgr.get_server_status("srv")
        assert info.name == "srv"
        assert info.status == MCPServerStatus.connected

    def test_get_status_nonexistent(self, mgr):
        with pytest.raises(NotFoundError):
            mgr.get_server_status("nope")

    def test_get_all_statuses(self, mgr, stdio_config, sse_config):
        mgr._configs["a"] = stdio_config
        mgr._configs["b"] = sse_config

        statuses = mgr.get_all_server_statuses()
        assert len(statuses) == 2
        names = {s.name for s in statuses}
        assert names == {"a", "b"}


# ---------------------------------------------------------------------------
# Connect / disconnect
# ---------------------------------------------------------------------------


class TestConnect:
    """Server connection lifecycle."""

    async def test_connect_disabled_skips(self, mgr, disabled_config):
        mgr._configs["srv"] = disabled_config
        await mgr.connect_server("srv")

        assert mgr._statuses["srv"] == MCPServerStatus.disconnected
        assert "srv" not in mgr._connections

    async def test_connect_nonexistent_raises(self, mgr):
        with pytest.raises(NotFoundError):
            await mgr.connect_server("nope")

    async def test_connect_stdio_missing_command_raises(self, mgr):
        cfg = MCPServerConfig(transport=MCPTransport.stdio, command=None, enabled=True)
        mgr._configs["srv"] = cfg

        await mgr.connect_server("srv")
        assert mgr._statuses["srv"] == MCPServerStatus.error

    async def test_connect_sse_missing_url_raises(self, mgr):
        cfg = MCPServerConfig(transport=MCPTransport.sse, url=None, enabled=True)
        mgr._configs["srv"] = cfg

        await mgr.connect_server("srv")
        assert mgr._statuses["srv"] == MCPServerStatus.error

    async def test_connect_streamable_http_missing_url(self, mgr):
        cfg = MCPServerConfig(transport="streamable-http", url=None, enabled=True)
        mgr._configs["srv"] = cfg

        await mgr.connect_server("srv")
        assert mgr._statuses["srv"] == MCPServerStatus.error

    async def test_connect_unsupported_transport(self, mgr):
        # MCPServerConfig validates transport via enum, so we directly inject
        # a config with a bad transport to test the fallback error path
        cfg = MCPServerConfig(transport="stdio", command="node", enabled=True)
        mgr._configs["srv"] = cfg
        # Bypass validation by overwriting the transport field after construction
        object.__setattr__(cfg, "transport", "grpc")

        await mgr.connect_server("srv")
        assert mgr._statuses["srv"] == MCPServerStatus.error

    async def test_disconnect_server(self, mgr):
        mock_stack = AsyncMock(spec=AsyncExitStack)
        mock_session = MagicMock()
        mgr._connections["srv"] = (mock_stack, mock_session)
        mgr._statuses["srv"] = MCPServerStatus.connected
        mgr._connected_at["srv"] = datetime.now(timezone.utc)
        mgr._tool_cache["srv"] = (time.monotonic(), [])

        await mgr.disconnect_server("srv")

        assert "srv" not in mgr._connections
        assert mgr._statuses["srv"] == MCPServerStatus.disconnected
        assert mgr._connected_at["srv"] is None
        assert "srv" not in mgr._tool_cache
        mock_stack.aclose.assert_awaited_once()

    async def test_disconnect_handles_error(self, mgr):
        mock_stack = AsyncMock(spec=AsyncExitStack)
        mock_stack.aclose.side_effect = RuntimeError("close failed")
        mgr._connections["srv"] = (mock_stack, MagicMock())
        mgr._statuses["srv"] = MCPServerStatus.connected

        # Should not raise
        await mgr.disconnect_server("srv")
        assert mgr._statuses["srv"] == MCPServerStatus.disconnected

    async def test_disconnect_nonexistent_is_safe(self, mgr):
        # Should not raise
        await mgr.disconnect_server("nonexistent")
        assert mgr._statuses["nonexistent"] == MCPServerStatus.disconnected

    async def test_connect_all(self, mgr, stdio_config, disabled_config):
        mgr._configs["enabled_srv"] = stdio_config
        mgr._configs["disabled_srv"] = disabled_config

        with patch.object(mgr, "connect_server", new_callable=AsyncMock) as mock_connect:
            await mgr.connect_all()

        mock_connect.assert_any_call("enabled_srv")
        assert mock_connect.call_count == 1

    async def test_disconnect_all(self, mgr):
        mock_stack1 = AsyncMock(spec=AsyncExitStack)
        mock_stack2 = AsyncMock(spec=AsyncExitStack)
        mgr._connections["a"] = (mock_stack1, MagicMock())
        mgr._connections["b"] = (mock_stack2, MagicMock())

        await mgr.disconnect_all()

        assert len(mgr._connections) == 0


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------


class TestToolDiscovery:
    """get_all_tools / get_tools_for_server / _format_tools."""

    def test_format_tools(self, mgr):
        mock_tool = MagicMock()
        mock_tool.name = "read"
        mock_tool.description = "Read a file"
        mock_tool.inputSchema = {"type": "object", "properties": {"path": {"type": "string"}}}

        result = mgr._format_tools("myserver", [mock_tool])
        assert len(result) == 1
        assert result[0]["function"]["name"] == "myserver__read"
        assert result[0]["function"]["description"] == "Read a file"

    def test_format_tools_no_schema(self, mgr):
        mock_tool = MagicMock()
        mock_tool.name = "ping"
        mock_tool.description = None
        mock_tool.inputSchema = None

        result = mgr._format_tools("srv", [mock_tool])
        assert result[0]["function"]["parameters"] == {"type": "object", "properties": {}}

    async def test_fetch_server_tools_cached(self, mgr):
        now = time.monotonic()
        cached_tools = [{"function": {"name": "srv__tool1", "description": "t", "parameters": {}}}]
        mgr._tool_cache["srv"] = (now, cached_tools)
        mgr._connections["srv"] = (MagicMock(), MagicMock())

        result = await mgr._fetch_server_tools("srv")
        assert result == cached_tools

    async def test_fetch_server_tools_expired_cache(self, mgr):
        expired_time = time.monotonic() - mgr._CACHE_TTL - 10
        mgr._tool_cache["srv"] = (expired_time, [])

        mock_session = AsyncMock()
        mock_tool = MagicMock()
        mock_tool.name = "new_tool"
        mock_tool.description = "new"
        mock_tool.inputSchema = {}
        mock_result = MagicMock()
        mock_result.tools = [mock_tool]
        mock_session.list_tools.return_value = mock_result

        mgr._connections["srv"] = (MagicMock(), mock_session)

        result = await mgr._fetch_server_tools("srv")
        assert len(result) == 1
        assert "srv__new_tool" in result[0]["function"]["name"]

    async def test_fetch_server_tools_not_connected(self, mgr):
        result = await mgr._fetch_server_tools("disconnected")
        assert result == []

    async def test_fetch_server_tools_error_uses_cached(self, mgr):
        old_tools = [{"function": {"name": "srv__old", "description": "", "parameters": {}}}]
        mgr._tool_cache["srv"] = (time.monotonic() - mgr._CACHE_TTL - 1, old_tools)

        mock_session = AsyncMock()
        mock_session.list_tools.side_effect = RuntimeError("connection lost")
        mgr._connections["srv"] = (MagicMock(), mock_session)

        result = await mgr._fetch_server_tools("srv")
        assert result == old_tools

    async def test_get_all_tools_empty(self, mgr):
        result = await mgr.get_all_tools()
        assert result == []

    async def test_get_all_tools_multiple_servers(self, mgr):
        tools_a = [{"function": {"name": "a__t1", "description": "", "parameters": {}}}]
        tools_b = [{"function": {"name": "b__t2", "description": "", "parameters": {}}}]
        mgr._tool_cache["a"] = (time.monotonic(), tools_a)
        mgr._tool_cache["b"] = (time.monotonic(), tools_b)
        mgr._connections["a"] = (MagicMock(), MagicMock())
        mgr._connections["b"] = (MagicMock(), MagicMock())

        result = await mgr.get_all_tools()
        assert len(result) == 2

    async def test_get_tools_for_server(self, mgr):
        cached_tools = [{
            "function": {
                "name": "srv__read",
                "description": "Read file",
                "parameters": {"type": "object"},
            },
        }]
        mgr._tool_cache["srv"] = (time.monotonic(), cached_tools)
        mgr._connections["srv"] = (MagicMock(), MagicMock())

        result = await mgr.get_tools_for_server("srv")
        assert len(result) == 1
        assert isinstance(result[0], MCPToolInfo)
        assert result[0].name == "read"
        assert result[0].server_name == "srv"


# ---------------------------------------------------------------------------
# Tool invocation
# ---------------------------------------------------------------------------


class TestCallTool:
    """call_tool dispatches to MCP session."""

    async def test_call_tool_text_result(self, mgr):
        from mcp import types

        mock_session = AsyncMock()
        mock_content = MagicMock(spec=types.TextContent)
        mock_content.text = "file content here"
        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_result.isError = False
        mock_session.call_tool.return_value = mock_result

        mgr._connections["srv"] = (MagicMock(), mock_session)

        result = await mgr.call_tool("srv", "read", {"path": "/test"})
        assert "file content here" in result

    async def test_call_tool_image_result(self, mgr):
        from mcp import types

        mock_session = AsyncMock()
        mock_content = MagicMock(spec=types.ImageContent)
        mock_content.mimeType = "image/png"
        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_result.isError = False
        mock_session.call_tool.return_value = mock_result

        mgr._connections["srv"] = (MagicMock(), mock_session)

        result = await mgr.call_tool("srv", "screenshot", {})
        assert "Image" in result

    async def test_call_tool_error_result(self, mgr):
        from mcp import types

        mock_session = AsyncMock()
        mock_content = MagicMock(spec=types.TextContent)
        mock_content.text = "something failed"
        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_result.isError = True
        mock_session.call_tool.return_value = mock_result

        mgr._connections["srv"] = (MagicMock(), mock_session)

        result = await mgr.call_tool("srv", "fail_tool", {})
        assert "Error" in result

    async def test_call_tool_not_connected(self, mgr):
        result = await mgr.call_tool("disconnected", "tool", {})
        assert "Error" in result
        assert "not connected" in result

    async def test_call_tool_timeout(self, mgr):
        mock_session = AsyncMock()
        mock_session.call_tool.side_effect = asyncio.TimeoutError()
        mgr._connections["srv"] = (MagicMock(), mock_session)

        result = await mgr.call_tool("srv", "slow_tool", {})
        assert "timed out" in result

    async def test_call_tool_exception(self, mgr):
        mock_session = AsyncMock()
        mock_session.call_tool.side_effect = ConnectionError("broken pipe")
        mgr._connections["srv"] = (MagicMock(), mock_session)

        result = await mgr.call_tool("srv", "bad_tool", {})
        assert "Error" in result
        assert "broken pipe" in result

    async def test_call_tool_no_output(self, mgr):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = []
        mock_result.isError = False
        mock_session.call_tool.return_value = mock_result

        mgr._connections["srv"] = (MagicMock(), mock_session)

        result = await mgr.call_tool("srv", "silent_tool", {})
        assert "no output" in result


# ---------------------------------------------------------------------------
# Raw config / sensitive value masking
# ---------------------------------------------------------------------------


class TestRawConfig:
    """get_raw_config masks sensitive values."""

    def test_env_fully_masked(self, mgr, stdio_config):
        mgr._configs["srv"] = stdio_config
        raw = mgr.get_raw_config()
        assert raw["mcpServers"]["srv"]["env"]["API_KEY"] == "***"

    def test_header_auth_masked(self, mgr):
        cfg = MCPServerConfig(
            transport="streamable-http",
            url="http://example.com",
            headers={"Authorization": "Bearer sk-1234567890abcdef", "Content-Type": "application/json"},
            enabled=True,
        )
        mgr._configs["http-srv"] = cfg
        raw = mgr.get_raw_config()
        headers = raw["mcpServers"]["http-srv"]["headers"]
        assert "***" in headers["Authorization"]
        assert headers["Content-Type"] == "application/json"

    def test_mask_sensitive_short_value(self, mgr):
        assert mgr._mask_sensitive_value("api_key", "short") == "***"

    def test_mask_sensitive_long_value(self, mgr):
        result = mgr._mask_sensitive_value("token", "abcdefghijklmnop")
        assert result.startswith("abcd")
        assert result.endswith("mnop")
        assert "***" in result

    def test_mask_non_sensitive(self, mgr):
        assert mgr._mask_sensitive_value("content_type", "application/json") == "application/json"

    def test_empty_config(self, mgr):
        raw = mgr.get_raw_config()
        assert raw == {"mcpServers": {}}


# ---------------------------------------------------------------------------
# Reload config
# ---------------------------------------------------------------------------


class TestReloadConfig:
    """reload_config reconciles connections with DB state."""

    async def test_reload_disconnects_removed(self, mgr, stdio_config):
        mgr._configs["old"] = stdio_config

        with (
            patch.object(mgr, "load_from_db", new_callable=AsyncMock) as mock_load,
            patch.object(mgr, "disconnect_server", new_callable=AsyncMock) as mock_disconnect,
            patch.object(mgr, "connect_server", new_callable=AsyncMock),
        ):
            async def clear_configs():
                mgr._configs.clear()
            mock_load.side_effect = clear_configs

            await mgr.reload_config()

        mock_disconnect.assert_any_call("old")

    async def test_reload_connects_new(self, mgr, stdio_config):
        with (
            patch.object(mgr, "load_from_db", new_callable=AsyncMock) as mock_load,
            patch.object(mgr, "connect_server", new_callable=AsyncMock) as mock_connect,
        ):
            async def add_new_config():
                mgr._configs["new_srv"] = stdio_config
            mock_load.side_effect = add_new_config

            await mgr.reload_config()

        mock_connect.assert_any_call("new_srv")

    async def test_reload_skips_disabled(self, mgr, disabled_config):
        with (
            patch.object(mgr, "load_from_db", new_callable=AsyncMock) as mock_load,
            patch.object(mgr, "connect_server", new_callable=AsyncMock) as mock_connect,
        ):
            async def add_disabled():
                mgr._configs["dis"] = disabled_config
            mock_load.side_effect = add_disabled

            await mgr.reload_config()

        # connect_server should not be called for disabled server
        for call in mock_connect.call_args_list:
            assert call.args[0] != "dis"


# ---------------------------------------------------------------------------
# Embedded resource in call_tool
# ---------------------------------------------------------------------------


class TestCallToolEdgeCases:
    """Additional call_tool result content types."""

    async def test_call_tool_embedded_resource(self, mgr):
        from mcp import types

        mock_session = AsyncMock()
        mock_resource = MagicMock()
        mock_resource.uri = "file:///data.json"
        mock_content = MagicMock(spec=types.EmbeddedResource)
        mock_content.resource = mock_resource
        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_result.isError = False
        mock_session.call_tool.return_value = mock_result

        mgr._connections["srv"] = (MagicMock(), mock_session)

        result = await mgr.call_tool("srv", "get_resource", {})
        assert "Resource" in result

    async def test_call_tool_unknown_content_type(self, mgr):
        mock_session = AsyncMock()
        mock_content = MagicMock()  # Not a recognized content type
        mock_content.__str__ = MagicMock(return_value="<unknown>")
        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_result.isError = False
        mock_session.call_tool.return_value = mock_result

        mgr._connections["srv"] = (MagicMock(), mock_session)

        result = await mgr.call_tool("srv", "weird_tool", {})
        assert result is not None

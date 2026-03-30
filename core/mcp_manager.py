import asyncio
import json
import logging
import shutil
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from open_agent.core.exceptions import ConfigError, NotFoundError
from open_agent.models.mcp import (
    MCPServerConfig,
    MCPServerInfo,
    MCPServerStatus,
    MCPToolInfo,
)

logger = logging.getLogger(__name__)

# Circuit Breaker configuration (inspired by ATLAS soft-fail pattern)
_CIRCUIT_FAILURE_THRESHOLD = 3
_CIRCUIT_RECOVERY_TIMEOUT = 60.0  # seconds before half-open


@dataclass
class _CircuitState:
    """Per-server circuit breaker state."""

    failures: int = 0
    last_failure_at: float = 0.0
    state: str = "closed"  # "closed" | "open" | "half-open"


def parse_namespaced_tool(name: str) -> Tuple[str, str]:
    """Parse 'server__tool' into ('server', 'tool')."""
    parts = name.split("__", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid namespaced tool name: {name}")
    return parts[0], parts[1]


class MCPClientManager:
    _CACHE_TTL = 300.0  # 5분 TTL

    def __init__(self):
        self._lock = asyncio.Lock()
        self._configs: Dict[str, MCPServerConfig] = {}
        self._connections: Dict[str, Tuple[AsyncExitStack, ClientSession]] = {}
        self._statuses: Dict[str, MCPServerStatus] = {}
        self._errors: Dict[str, Optional[str]] = {}
        self._connected_at: Dict[str, Optional[datetime]] = {}
        # Phase 1: Tool schema cache (server_name -> (timestamp, tools))
        self._tool_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self._circuits: Dict[str, _CircuitState] = {}

    def _check_circuit(self, server_name: str) -> bool:
        """Return True if the request should proceed, False if circuit is open."""
        circuit = self._circuits.get(server_name)
        if circuit is None or circuit.state == "closed":
            return True
        if circuit.state == "open":
            if time.monotonic() - circuit.last_failure_at > _CIRCUIT_RECOVERY_TIMEOUT:
                circuit.state = "half-open"
                logger.info(
                    "Circuit breaker half-open for '%s', allowing probe request", server_name
                )
                return True
            return False
        # half-open: allow one probe request
        return True

    def _record_success(self, server_name: str) -> None:
        """Record a successful call — reset circuit if half-open."""
        circuit = self._circuits.get(server_name)
        if circuit is None:
            return
        if circuit.state == "half-open":
            logger.info("Circuit breaker closed for '%s' after successful probe", server_name)
        circuit.failures = 0
        circuit.state = "closed"

    def _record_failure(self, server_name: str) -> None:
        """Record a failed call — open circuit if threshold reached."""
        circuit = self._circuits.setdefault(server_name, _CircuitState())
        circuit.failures += 1
        circuit.last_failure_at = time.monotonic()
        if circuit.failures >= _CIRCUIT_FAILURE_THRESHOLD and circuit.state != "open":
            circuit.state = "open"
            logger.warning(
                "Circuit breaker OPEN for '%s' after %d failures (recovery in %.0fs)",
                server_name,
                circuit.failures,
                _CIRCUIT_RECOVERY_TIMEOUT,
            )

    async def load_from_db(self) -> None:
        """Load MCP server configs from database."""
        async with self._lock:
            from core.db.engine import async_session_factory
            from core.db.repositories.mcp_config_repo import MCPConfigRepository

            async with async_session_factory() as session:
                repo = MCPConfigRepository(session)
                rows = await repo.get_all()
                self._configs.clear()
                for row in rows:
                    self._configs[row.name] = MCPServerConfig(
                        transport=row.transport,
                        command=row.command,
                        args=row.args,
                        env=row.env,
                        url=row.url,
                        headers=row.headers,
                        enabled=row.enabled,
                    )
                logger.info(f"Loaded {len(self._configs)} MCP server configs from database")

    async def _save_config(self) -> None:
        """Persist all configs to database."""
        from core.db.engine import async_session_factory
        from core.db.models.mcp_config import MCPConfigORM

        async with async_session_factory() as session:
            for name, cfg in self._configs.items():
                orm = MCPConfigORM(
                    name=name,
                    transport=cfg.transport,
                    command=cfg.command,
                    args=cfg.args,
                    env=cfg.env,
                    url=cfg.url,
                    headers=cfg.headers,
                    enabled=cfg.enabled,
                )
                await session.merge(orm)
            await session.commit()

    async def connect_server(self, server_name: str) -> None:
        """Connect to a single MCP server by name."""
        if server_name not in self._configs:
            raise NotFoundError(f"Server '{server_name}' not found in config")

        config = self._configs[server_name]
        if not config.enabled:
            logger.info(f"Server '{server_name}' is disabled, skipping connection")
            self._statuses[server_name] = MCPServerStatus.disconnected
            return

        # Disconnect first if already connected
        if server_name in self._connections:
            await self.disconnect_server(server_name)

        self._statuses[server_name] = MCPServerStatus.connecting
        self._errors[server_name] = None

        try:
            exit_stack = AsyncExitStack()
            await exit_stack.__aenter__()

            if config.transport == "stdio":
                if not config.command:
                    raise ConfigError(f"Server '{server_name}': stdio transport requires 'command'")
                # command가 PATH에 존재하는지 확인
                if not shutil.which(config.command):
                    raise ConfigError(
                        f"Server '{server_name}': command not found in PATH: '{config.command}'"
                    )
                params = StdioServerParameters(
                    command=config.command,
                    args=config.args or [],
                    env=config.env,
                )
                read_stream, write_stream = await exit_stack.enter_async_context(
                    stdio_client(params)
                )
            elif config.transport == "sse":
                if not config.url:
                    raise ConfigError(f"Server '{server_name}': sse transport requires 'url'")
                parsed = urlparse(config.url)
                if parsed.scheme not in ("http", "https"):
                    raise ConfigError(
                        f"Server '{server_name}': URL scheme must be http or https, got '{parsed.scheme}'"
                    )
                read_stream, write_stream = await exit_stack.enter_async_context(
                    sse_client(config.url)
                )
            elif config.transport == "streamable-http":
                if not config.url:
                    raise ConfigError(
                        f"Server '{server_name}': streamable-http transport requires 'url'"
                    )
                parsed = urlparse(config.url)
                if parsed.scheme not in ("http", "https"):
                    raise ConfigError(
                        f"Server '{server_name}': URL scheme must be http or https, got '{parsed.scheme}'"
                    )
                if config.headers:
                    http_client = await exit_stack.enter_async_context(
                        httpx.AsyncClient(headers=config.headers)
                    )
                    result = await exit_stack.enter_async_context(
                        streamable_http_client(config.url, http_client=http_client)
                    )
                else:
                    result = await exit_stack.enter_async_context(
                        streamable_http_client(config.url)
                    )
                read_stream, write_stream = result[0], result[1]
            else:
                raise ConfigError(f"Unsupported transport: {config.transport}")

            session = await exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()

            self._connections[server_name] = (exit_stack, session)
            self._statuses[server_name] = MCPServerStatus.connected
            self._connected_at[server_name] = datetime.now(timezone.utc)
            self._tool_cache.pop(server_name, None)  # 캐시 무효화
            # Reset circuit breaker on successful connection
            self._circuits.pop(server_name, None)
            logger.info(f"Connected to MCP server: {server_name}")

        except Exception as e:
            self._statuses[server_name] = MCPServerStatus.error
            self._errors[server_name] = str(e)
            logger.error(f"Failed to connect to MCP server '{server_name}': {e}")
            # Clean up the exit stack on failure
            try:
                await exit_stack.aclose()
            except Exception as exc:
                logger.warning(f"Failed to clean up exit stack for '{server_name}'", exc_info=exc)

    async def disconnect_server(self, server_name: str) -> None:
        """Disconnect from a single MCP server."""
        if server_name in self._connections:
            exit_stack, _ = self._connections.pop(server_name)
            try:
                await exit_stack.aclose()
            except Exception as e:
                logger.warning(f"Error disconnecting server '{server_name}': {e}")
        self._statuses[server_name] = MCPServerStatus.disconnected
        self._connected_at[server_name] = None
        self._tool_cache.pop(server_name, None)  # 캐시 무효화
        logger.info(f"Disconnected from MCP server: {server_name}")

    async def connect_all(self) -> None:
        """Connect to all enabled servers."""
        for name in self._configs:
            if self._configs[name].enabled:
                await self.connect_server(name)

    async def disconnect_all(self) -> None:
        """Disconnect from all servers."""
        for name in list(self._connections.keys()):
            await self.disconnect_server(name)

    @staticmethod
    def _format_tools(server_name: str, tools) -> List[Dict[str, Any]]:
        """MCP 도구 목록을 OpenAI function format으로 변환."""
        return [
            {
                "type": "function",
                "function": {
                    "name": f"{server_name}__{tool.name}",
                    "description": tool.description or "",
                    "parameters": tool.inputSchema
                    if tool.inputSchema
                    else {"type": "object", "properties": {}},
                },
            }
            for tool in tools
        ]

    async def _fetch_server_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """단일 서버에서 도구 목록 조회 (캐시 우선)."""
        now = time.monotonic()
        if server_name in self._tool_cache:
            cached_at, cached_tools = self._tool_cache[server_name]
            if (now - cached_at) < self._CACHE_TTL:
                return cached_tools

        # Circuit breaker: skip fetch if circuit is open
        if not self._check_circuit(server_name):
            # Return cached tools if available, empty list otherwise
            if server_name in self._tool_cache:
                return self._tool_cache[server_name][1]
            return []

        if server_name not in self._connections:
            return []
        _, session = self._connections[server_name]
        try:
            result = await session.list_tools()
            server_tools = self._format_tools(server_name, result.tools)
            self._tool_cache[server_name] = (now, server_tools)
            self._record_success(server_name)
            return server_tools
        except Exception as e:
            logger.error(f"Failed to list tools from '{server_name}': {e}")
            self._record_failure(server_name)
            if server_name in self._tool_cache:
                return self._tool_cache[server_name][1]
            return []

    async def get_all_tools(self) -> List[Dict[str, Any]]:
        """Get all tools from connected servers in OpenAI function format (캐시 + 병렬 조회)."""
        server_names = list(self._connections.keys())
        if not server_names:
            return []
        results = await asyncio.gather(*(self._fetch_server_tools(name) for name in server_names))
        all_tools = []
        for tools in results:
            all_tools.extend(tools)
        return all_tools

    async def get_tools_for_server(self, server_name: str) -> List[MCPToolInfo]:
        """Get tools from a specific server (캐시 활용)."""
        cached_tools = await self._fetch_server_tools(server_name)
        return [
            MCPToolInfo(
                name=t["function"]["name"].split("__", 1)[1]
                if "__" in t["function"]["name"]
                else t["function"]["name"],
                description=t["function"].get("description"),
                input_schema=t["function"].get("parameters", {}),
                server_name=server_name,
            )
            for t in cached_tools
        ]

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call a tool on a specific server."""
        if server_name not in self._connections:
            return f"Error: Server '{server_name}' is not connected"

        from open_agent.core.settings_manager import settings_manager

        approval_settings = settings_manager.settings.approval
        if (
            approval_settings.allowed_mcp_servers
            and server_name not in approval_settings.allowed_mcp_servers
        ):
            return f"Error: MCP server '{server_name}' is not allowed by current policy"

        full_tool_name = f"{server_name}__{tool_name}"
        if (
            approval_settings.allowed_tool_names
            and full_tool_name not in approval_settings.allowed_tool_names
        ):
            return f"Error: MCP tool '{full_tool_name}' is not allowed by current policy"

        # Circuit breaker check
        if not self._check_circuit(server_name):
            return (
                f"Error: Server '{server_name}' circuit breaker is open "
                f"(too many failures, will retry after {_CIRCUIT_RECOVERY_TIMEOUT:.0f}s)"
            )

        _, session = self._connections[server_name]
        try:
            sanitized = json.loads(json.dumps(arguments))
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=sanitized),
                timeout=120,
            )
            # Extract text from result content
            texts = []
            for content in result.content:
                if isinstance(content, types.TextContent):
                    texts.append(content.text)
                elif isinstance(content, types.ImageContent):
                    texts.append(f"[Image: {content.mimeType}]")
                elif isinstance(content, types.EmbeddedResource):
                    texts.append(f"[Resource: {content.resource.uri}]")
                else:
                    texts.append(str(content))
            output = "\n".join(texts) if texts else "Tool executed successfully (no output)"
            if result.isError:
                self._record_failure(server_name)
                return f"Error: MCP tool '{tool_name}' failed: {output}"
            self._record_success(server_name)
            return output
        except asyncio.TimeoutError:
            self._record_failure(server_name)
            return f"Error: MCP tool '{tool_name}' on '{server_name}' timed out after 120s"
        except Exception as e:
            self._record_failure(server_name)
            return f"Error calling tool '{tool_name}' on '{server_name}': {str(e)}"

    def get_server_status(self, name: str) -> MCPServerInfo:
        """Get status info for a specific server."""
        if name not in self._configs:
            raise NotFoundError(f"Server '{name}' not found")
        return MCPServerInfo(
            name=name,
            config=self._configs[name],
            status=self._statuses.get(name, MCPServerStatus.disconnected),
            error=self._errors.get(name),
            connected_at=self._connected_at.get(name),
        )

    def get_all_server_statuses(self) -> List[MCPServerInfo]:
        """Get status info for all configured servers."""
        return [self.get_server_status(name) for name in self._configs]

    async def reload_config(self) -> None:
        """Reload config from DB and reconcile connections."""
        old_configs = dict(self._configs)
        await self.load_from_db()

        # Disconnect removed servers
        for name in old_configs:
            if name not in self._configs:
                await self.disconnect_server(name)

        # Connect new or changed servers
        for name, config in self._configs.items():
            old = old_configs.get(name)
            if old is None or old != config:
                if config.enabled:
                    await self.connect_server(name)
                elif name in self._connections:
                    await self.disconnect_server(name)

    # --- Config mutation helpers ---

    async def add_server_config(self, name: str, config: MCPServerConfig) -> None:
        """Add a server to config and persist."""
        async with self._lock:
            self._configs[name] = config
            await self._save_config()

    async def update_server_config(self, name: str, updates: Dict[str, Any]) -> MCPServerConfig:
        """Partially update a server config and persist."""
        async with self._lock:
            if name not in self._configs:
                raise NotFoundError(f"Server '{name}' not found")
            current = self._configs[name].model_dump()
            current.update({k: v for k, v in updates.items() if v is not None})
            self._configs[name] = MCPServerConfig(**current)
            await self._save_config()
            return self._configs[name]

    async def remove_server_config(self, name: str) -> None:
        """Remove a server from config and persist."""
        async with self._lock:
            if name in self._configs:
                del self._configs[name]
                from core.db.engine import async_session_factory
                from core.db.repositories.mcp_config_repo import MCPConfigRepository

                async with async_session_factory() as session:
                    repo = MCPConfigRepository(session)
                    await repo.delete_by_id(name)
                    await session.commit()

    @staticmethod
    def _mask_sensitive_value(key: str, value: str) -> str:
        """민감한 키의 값을 마스킹"""
        sensitive_keywords = {
            "auth",
            "token",
            "key",
            "secret",
            "password",
            "credential",
            "api_key",
            "apikey",
        }
        if any(kw in key.lower() for kw in sensitive_keywords):
            if len(value) <= 8:
                return "***"
            return value[:4] + "***" + value[-4:]
        return value

    def get_raw_config(self) -> Dict[str, Any]:
        """Return the raw mcpServers config dict with sensitive values masked."""
        result: Dict[str, Any] = {}
        for name, cfg in self._configs.items():
            cfg_dict = cfg.model_dump(exclude_none=True)
            # env 값 전체 마스킹
            if "env" in cfg_dict and isinstance(cfg_dict["env"], dict):
                cfg_dict["env"] = {k: "***" for k in cfg_dict["env"]}
            # headers 중 민감 키 마스킹
            if "headers" in cfg_dict and isinstance(cfg_dict["headers"], dict):
                cfg_dict["headers"] = {
                    k: self._mask_sensitive_value(k, v) if isinstance(v, str) else v
                    for k, v in cfg_dict["headers"].items()
                }
            result[name] = cfg_dict
        return {"mcpServers": result}


mcp_manager = MCPClientManager()

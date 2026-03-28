import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from open_agent.core.exceptions import ConfigError, NotFoundError
from open_agent.models.mcp import (
    MCPServerConfig,
    MCPServerInfo,
    MCPServerStatus,
    MCPToolInfo,
)

logger = logging.getLogger(__name__)


def parse_namespaced_tool(name: str) -> Tuple[str, str]:
    """Parse 'server__tool' into ('server', 'tool')."""
    parts = name.split("__", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid namespaced tool name: {name}")
    return parts[0], parts[1]


class MCPClientManager:
    _CACHE_TTL = 300.0  # 5분 TTL

    def __init__(self):
        self._configs: Dict[str, MCPServerConfig] = {}
        self._connections: Dict[str, Tuple[AsyncExitStack, ClientSession]] = {}
        self._statuses: Dict[str, MCPServerStatus] = {}
        self._errors: Dict[str, Optional[str]] = {}
        self._connected_at: Dict[str, Optional[datetime]] = {}
        self._config_path: Optional[Path] = None
        # Phase 1: Tool schema cache (server_name -> (timestamp, tools))
        self._tool_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}

    def load_config(self, config_path: str) -> None:
        """Load mcp.json configuration."""
        path = Path(config_path)
        if not path.is_absolute():
            from open_agent.config import get_config_path
            path = get_config_path(config_path)
        self._config_path = path

        if not path.exists():
            logger.warning(f"Config file not found: {path}, creating empty config")
            path.write_text(json.dumps({"mcpServers": {}}, indent=2), encoding="utf-8")
            self._configs = {}
            return

        data = json.loads(path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        self._configs = {
            name: MCPServerConfig(**cfg) for name, cfg in servers.items()
        }
        logger.info(f"Loaded {len(self._configs)} MCP server configs from {path}")

    def _save_config(self) -> None:
        """Persist current configs to mcp.json."""
        if not self._config_path:
            return
        data = {
            "mcpServers": {
                name: cfg.model_dump(exclude_none=True)
                for name, cfg in self._configs.items()
            }
        }
        self._config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

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
                    raise ConfigError(f"Server '{server_name}': command not found in PATH: '{config.command}'")
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
                    raise ConfigError(f"Server '{server_name}': URL scheme must be http or https, got '{parsed.scheme}'")
                read_stream, write_stream = await exit_stack.enter_async_context(
                    sse_client(config.url)
                )
            elif config.transport == "streamable-http":
                if not config.url:
                    raise ConfigError(f"Server '{server_name}': streamable-http transport requires 'url'")
                parsed = urlparse(config.url)
                if parsed.scheme not in ("http", "https"):
                    raise ConfigError(f"Server '{server_name}': URL scheme must be http or https, got '{parsed.scheme}'")
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

            session = await exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()

            self._connections[server_name] = (exit_stack, session)
            self._statuses[server_name] = MCPServerStatus.connected
            self._connected_at[server_name] = datetime.now(timezone.utc)
            self._tool_cache.pop(server_name, None)  # 캐시 무효화
            logger.info(f"Connected to MCP server: {server_name}")

        except Exception as e:
            self._statuses[server_name] = MCPServerStatus.error
            self._errors[server_name] = str(e)
            logger.error(f"Failed to connect to MCP server '{server_name}': {e}")
            # Clean up the exit stack on failure
            try:
                await exit_stack.aclose()
            except Exception:
                pass

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
                    "parameters": tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
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

        if server_name not in self._connections:
            return []
        _, session = self._connections[server_name]
        try:
            result = await session.list_tools()
            server_tools = self._format_tools(server_name, result.tools)
            self._tool_cache[server_name] = (now, server_tools)
            return server_tools
        except Exception as e:
            logger.error(f"Failed to list tools from '{server_name}': {e}")
            # 캐시에 이전 값이 있으면 사용
            if server_name in self._tool_cache:
                return self._tool_cache[server_name][1]
            return []

    async def get_all_tools(self) -> List[Dict[str, Any]]:
        """Get all tools from connected servers in OpenAI function format (캐시 + 병렬 조회)."""
        server_names = list(self._connections.keys())
        if not server_names:
            return []
        results = await asyncio.gather(
            *(self._fetch_server_tools(name) for name in server_names)
        )
        all_tools = []
        for tools in results:
            all_tools.extend(tools)
        return all_tools

    async def get_tools_for_server(self, server_name: str) -> List[MCPToolInfo]:
        """Get tools from a specific server (캐시 활용)."""
        cached_tools = await self._fetch_server_tools(server_name)
        return [
            MCPToolInfo(
                name=t["function"]["name"].split("__", 1)[1] if "__" in t["function"]["name"] else t["function"]["name"],
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
                return f"Error: MCP tool '{tool_name}' failed: {output}"
            return output
        except asyncio.TimeoutError:
            return f"Error: MCP tool '{tool_name}' on '{server_name}' timed out after 120s"
        except Exception as e:
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
        """Reload config and reconcile connections."""
        if not self._config_path:
            return

        old_configs = dict(self._configs)
        self.load_config(str(self._config_path))

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

    def add_server_config(self, name: str, config: MCPServerConfig) -> None:
        """Add a server to config and persist."""
        self._configs[name] = config
        self._save_config()

    def update_server_config(self, name: str, updates: Dict[str, Any]) -> MCPServerConfig:
        """Partially update a server config and persist."""
        if name not in self._configs:
            raise NotFoundError(f"Server '{name}' not found")
        current = self._configs[name].model_dump()
        current.update({k: v for k, v in updates.items() if v is not None})
        self._configs[name] = MCPServerConfig(**current)
        self._save_config()
        return self._configs[name]

    def remove_server_config(self, name: str) -> None:
        """Remove a server from config and persist."""
        if name in self._configs:
            del self._configs[name]
            self._save_config()

    @staticmethod
    def _mask_sensitive_value(key: str, value: str) -> str:
        """민감한 키의 값을 마스킹"""
        sensitive_keywords = {"auth", "token", "key", "secret", "password", "credential", "api_key", "apikey"}
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

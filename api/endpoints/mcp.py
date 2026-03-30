from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from open_agent.core.mcp_manager import mcp_manager
from open_agent.models.mcp import MCPServerConfig, MCPServerInfo, MCPToolInfo
from pydantic import BaseModel

from core.auth.dependencies import require_admin, require_user

router = APIRouter()


def _mask_sensitive_value(key: str, value: str) -> str:
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
    if any(keyword in key.lower() for keyword in sensitive_keywords):
        if len(value) <= 8:
            return "***"
        return value[:4] + "***" + value[-4:]
    return value


def _sanitize_config(config: MCPServerConfig) -> MCPServerConfig:
    config_data = config.model_dump()

    if isinstance(config_data.get("env"), dict):
        config_data["env"] = dict.fromkeys(config_data["env"], "***")

    if isinstance(config_data.get("headers"), dict):
        config_data["headers"] = {
            key: _mask_sensitive_value(key, value) if isinstance(value, str) else value
            for key, value in config_data["headers"].items()
        }

    return MCPServerConfig(**config_data)


def _sanitize_server_info(info: MCPServerInfo) -> MCPServerInfo:
    return info.model_copy(update={"config": _sanitize_config(info.config)})


# --- Request schemas ---


class AddServerRequest(BaseModel):
    name: str
    config: MCPServerConfig


class UpdateServerRequest(BaseModel):
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    enabled: bool | None = None


# --- Config endpoints ---


@router.get("/config")
async def get_config(current_user: Annotated[dict, Depends(require_user)]) -> dict[str, Any]:
    """Return full mcp.json content."""
    return mcp_manager.get_raw_config()


@router.put("/config")
async def update_config(
    config: dict[str, Any], current_user: Annotated[dict, Depends(require_admin)]
) -> dict[str, Any]:
    """Overwrite full mcp.json and reload."""
    servers = config.get("mcpServers", {})
    # Validate all configs
    for _name, cfg in servers.items():
        MCPServerConfig(**cfg)
    # Replace configs
    for name in list(mcp_manager._configs.keys()):
        await mcp_manager.remove_server_config(name)
    for name, cfg in servers.items():
        await mcp_manager.add_server_config(name, MCPServerConfig(**cfg))
    await mcp_manager.reload_config()
    return mcp_manager.get_raw_config()


# --- Server CRUD endpoints ---


@router.get("/servers", response_model=list[MCPServerInfo])
async def list_servers(current_user: Annotated[dict, Depends(require_user)]):
    """List all MCP servers with status."""
    infos = mcp_manager.get_all_server_statuses()
    # Populate tools for connected servers
    for info in infos:
        if info.status == "connected":
            info.tools = await mcp_manager.get_tools_for_server(info.name)
    return [_sanitize_server_info(info) for info in infos]


@router.get("/servers/{name}", response_model=MCPServerInfo)
async def get_server(name: str, current_user: Annotated[dict, Depends(require_user)]):
    """Get specific server details."""
    try:
        info = mcp_manager.get_server_status(name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found") from None
    if info.status == "connected":
        info.tools = await mcp_manager.get_tools_for_server(name)
    return _sanitize_server_info(info)


@router.post("/servers", response_model=MCPServerInfo)
async def add_server(req: AddServerRequest, current_user: Annotated[dict, Depends(require_admin)]):
    """Add a new MCP server and connect."""
    if req.name in mcp_manager._configs:
        raise HTTPException(status_code=409, detail=f"Server '{req.name}' already exists")
    await mcp_manager.add_server_config(req.name, req.config)
    if req.config.enabled:
        await mcp_manager.connect_server(req.name)
    info = mcp_manager.get_server_status(req.name)
    if info.status == "connected":
        info.tools = await mcp_manager.get_tools_for_server(req.name)
    return _sanitize_server_info(info)


@router.delete("/servers/{name}")
async def delete_server(name: str, current_user: Annotated[dict, Depends(require_admin)]):
    """Delete an MCP server."""
    if name not in mcp_manager._configs:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
    await mcp_manager.disconnect_server(name)
    await mcp_manager.remove_server_config(name)
    return {"message": f"Server '{name}' deleted"}


@router.patch("/servers/{name}", response_model=MCPServerInfo)
async def update_server(
    name: str, req: UpdateServerRequest, current_user: Annotated[dict, Depends(require_admin)]
):
    """Update server config (partial). Reconnects if transport/connection params change."""
    if name not in mcp_manager._configs:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")

    updates = req.model_dump(exclude_none=True)
    old_config = mcp_manager._configs[name].model_dump()

    await mcp_manager.update_server_config(name, updates)
    new_config = mcp_manager._configs[name]

    # Determine if reconnection needed
    connection_fields = {"transport", "command", "args", "env", "url", "headers"}
    needs_reconnect = any(
        updates.get(f) is not None and updates[f] != old_config.get(f) for f in connection_fields
    )

    if "enabled" in updates:
        if not new_config.enabled and name in mcp_manager._connections:
            await mcp_manager.disconnect_server(name)
        elif new_config.enabled and name not in mcp_manager._connections:
            await mcp_manager.connect_server(name)
            needs_reconnect = False

    if needs_reconnect and new_config.enabled:
        await mcp_manager.connect_server(name)

    info = mcp_manager.get_server_status(name)
    if info.status == "connected":
        info.tools = await mcp_manager.get_tools_for_server(name)
    return _sanitize_server_info(info)


# --- Connection control endpoints ---


@router.post("/servers/{name}/connect", response_model=MCPServerInfo)
async def connect_server(name: str, current_user: Annotated[dict, Depends(require_admin)]):
    """Manually connect to a server."""
    if name not in mcp_manager._configs:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
    await mcp_manager.connect_server(name)
    info = mcp_manager.get_server_status(name)
    if info.status == "connected":
        info.tools = await mcp_manager.get_tools_for_server(name)
    return _sanitize_server_info(info)


@router.post("/servers/{name}/disconnect", response_model=MCPServerInfo)
async def disconnect_server(name: str, current_user: Annotated[dict, Depends(require_admin)]):
    """Manually disconnect from a server."""
    if name not in mcp_manager._configs:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
    await mcp_manager.disconnect_server(name)
    return _sanitize_server_info(mcp_manager.get_server_status(name))


@router.post("/servers/{name}/restart", response_model=MCPServerInfo)
async def restart_server(name: str, current_user: Annotated[dict, Depends(require_admin)]):
    """Restart a server (disconnect + connect)."""
    if name not in mcp_manager._configs:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
    await mcp_manager.disconnect_server(name)
    await mcp_manager.connect_server(name)
    info = mcp_manager.get_server_status(name)
    if info.status == "connected":
        info.tools = await mcp_manager.get_tools_for_server(name)
    return _sanitize_server_info(info)


# --- Tool endpoints ---


@router.get("/tools", response_model=list[MCPToolInfo])
async def list_all_tools(current_user: Annotated[dict, Depends(require_user)]):
    """List all tools from all connected servers."""
    all_tools: list[MCPToolInfo] = []
    for name in mcp_manager._connections:
        tools = await mcp_manager.get_tools_for_server(name)
        all_tools.extend(tools)
    return all_tools


@router.get("/tools/{server_name}", response_model=list[MCPToolInfo])
async def list_server_tools(server_name: str, current_user: Annotated[dict, Depends(require_user)]):
    """List tools from a specific server."""
    if server_name not in mcp_manager._configs:
        raise HTTPException(status_code=404, detail=f"Server '{server_name}' not found")
    return await mcp_manager.get_tools_for_server(server_name)


# --- Reload endpoint ---


@router.post("/reload")
async def reload_config(current_user: Annotated[dict, Depends(require_admin)]):
    """Reload mcp.json and reconcile connections."""
    await mcp_manager.reload_config()
    return {"message": "Config reloaded", "servers": len(mcp_manager._configs)}

from enum import Enum
from typing import Dict, List, Any, Optional
from datetime import datetime
from pydantic import BaseModel


class MCPServerConfig(BaseModel):
    transport: str = "stdio"  # stdio | sse | streamable-http
    command: Optional[str] = None  # stdio only
    args: Optional[List[str]] = None  # stdio only
    env: Optional[Dict[str, str]] = None  # stdio only
    url: Optional[str] = None  # sse / streamable-http
    headers: Optional[Dict[str, str]] = None  # streamable-http
    enabled: bool = True


class MCPServerStatus(str, Enum):
    connecting = "connecting"
    connected = "connected"
    disconnected = "disconnected"
    error = "error"


class MCPToolInfo(BaseModel):
    name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = {}
    server_name: str


class MCPServerInfo(BaseModel):
    name: str
    config: MCPServerConfig
    status: MCPServerStatus
    tools: List[MCPToolInfo] = []
    error: Optional[str] = None
    connected_at: Optional[datetime] = None

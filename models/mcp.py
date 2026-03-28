from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MCPTransport(str, Enum):
    stdio = "stdio"
    sse = "sse"
    streamable_http = "streamable-http"


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    transport: MCPTransport = MCPTransport.stdio
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
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    server_name: str


class MCPServerInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    name: str
    config: MCPServerConfig
    status: MCPServerStatus
    tools: List[MCPToolInfo] = Field(default_factory=list)
    error: Optional[str] = None
    connected_at: Optional[datetime] = None

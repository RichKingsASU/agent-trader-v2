from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


JsonObject = Dict[str, Any]


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: Optional[Union[str, int]] = None
    method: str
    params: Optional[JsonObject] = None


class JsonRpcResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: Union[str, int, None]
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None


class MCPTextContent(BaseModel):
    type: Literal["text"] = "text"
    text: str


class MCPJsonContent(BaseModel):
    type: Literal["json"] = "json"
    json: Any


MCPContent = Union[MCPTextContent, MCPJsonContent]


class MCPTool(BaseModel):
    name: str
    description: str
    inputSchema: JsonObject = Field(default_factory=dict)


class MCPServerInfo(BaseModel):
    name: str
    version: str


class MCPInitializeResult(BaseModel):
    protocolVersion: str = "2024-11-05"
    serverInfo: MCPServerInfo
    capabilities: JsonObject = Field(default_factory=dict)


class MCPToolsListResult(BaseModel):
    tools: List[MCPTool]


class MCPToolsCallResult(BaseModel):
    content: List[MCPContent]
    isError: bool = False


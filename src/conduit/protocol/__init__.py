# pyright: reportUnusedImport=false
# pyright: reportUnsupportedDunderAll=false

from .base import (
    Error,
    Notification,
    PaginatedRequest,
    PaginatedResult,
    ProtocolModel,
    Request,
    Result,
)
from .common import CancelledNotification, PingRequest, ProgressNotification
from .content import Annotations, EmbeddedResource, ImageContent, TextContent
from .initialization import InitializedNotification, InitializeRequest, InitializeResult
from .jsonrpc import JSONRPCError, JSONRPCNotification, JSONRPCRequest, JSONRPCResponse
from .prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
)
from .resources import (
    ListResourcesRequest,
    ListResourcesResult,
    ReadResourceRequest,
    ReadResourceResult,
)
from .tools import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    ToolListChangedNotification,
)
from .unions import (
    ClientNotification,
    ClientRequest,
    JSONRPCMessage,
    ServerNotification,
    ServerRequest,
)

_BASE_TYPES = [
    "Error",
    "Notification",
    "PaginatedRequest",
    "PaginatedResult",
    "ProtocolModel",
    "Request",
    "Result",
]

_COMMON_TYPES = [
    "CancelledNotification",
    "PingRequest",
    "ProgressNotification",
]

_CONTENT_TYPES = [
    "Annotations",
    "EmbeddedResource",
    "ImageContent",
    "TextContent",
]

_INITIALIZATION_TYPES = [
    "InitializedNotification",
    "InitializeRequest",
    "InitializeResult",
]

_JSONRPC_TYPES = [
    "JSONRPCError",
    "JSONRPCNotification",
    "JSONRPCRequest",
    "JSONRPCResponse",
]

_PROMPT_TYPES = [
    "GetPromptRequest",
    "GetPromptResult",
    "ListPromptsRequest",
    "ListPromptsResult",
]

_RESOURCE_TYPES = [
    "ListResourcesRequest",
    "ListResourcesResult",
    "ReadResourceRequest",
    "ReadResourceResult",
]

_TOOL_TYPES = [
    "CallToolRequest",
    "CallToolResult",
    "ListToolsRequest",
    "ListToolsResult",
    "ToolListChangedNotification",
]

_UNION_TYPES = [
    "ClientNotification",
    "ClientRequest",
    "JSONRPCMessage",
    "ServerNotification",
    "ServerRequest",
]

_ALL_TYPES = (
    _BASE_TYPES
    + _COMMON_TYPES
    + _CONTENT_TYPES
    + _INITIALIZATION_TYPES
    + _JSONRPC_TYPES
    + _PROMPT_TYPES
    + _RESOURCE_TYPES
    + _TOOL_TYPES
    + _UNION_TYPES
)

__all__ = _ALL_TYPES

from conduit.protocol.common import (
    CancelledNotification,
    EmptyResult,
    PingRequest,
    ProgressNotification,
)
from conduit.protocol.completions import CompleteRequest, CompleteResult
from conduit.protocol.elicitation import ElicitRequest, ElicitResult
from conduit.protocol.initialization import (
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
)
from conduit.protocol.jsonrpc import (
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)
from conduit.protocol.logging import LoggingMessageNotification, SetLevelRequest
from conduit.protocol.prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
    PromptListChangedNotification,
)
from conduit.protocol.resources import (
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    ReadResourceRequest,
    ReadResourceResult,
    ResourceListChangedNotification,
    ResourceUpdatedNotification,
    SubscribeRequest,
    UnsubscribeRequest,
)
from conduit.protocol.roots import ListRootsResult, RootsListChangedNotification
from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult
from conduit.protocol.tools import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    ToolListChangedNotification,
)

# ----------- Client Requests -------------
ClientRequest = (
    PingRequest
    | InitializeRequest
    | CompleteRequest
    | SetLevelRequest
    | GetPromptRequest
    | ListPromptsRequest
    | ListResourcesRequest
    | ListResourceTemplatesRequest
    | ReadResourceRequest
    | SubscribeRequest
    | UnsubscribeRequest
    | CallToolRequest
    | ListToolsRequest
)

# ----------- Client Notifications -------------
ClientNotification = (
    CancelledNotification
    | ProgressNotification
    | InitializedNotification
    | RootsListChangedNotification
)

# ----------- Client Results -------------
ClientResult = EmptyResult | CreateMessageResult | ListRootsResult | ElicitResult

# ----------- Server Requests -------------
ServerRequest = PingRequest | CreateMessageRequest | ListToolsRequest | ElicitRequest

# ----------- Server Notifications -------------
ServerNotification = (
    CancelledNotification
    | ProgressNotification
    | LoggingMessageNotification
    | ResourceUpdatedNotification
    | ResourceListChangedNotification
    | ToolListChangedNotification
    | PromptListChangedNotification
)

# ----------- Server Results -------------
ServerResult = (
    EmptyResult
    | InitializeResult
    | CompleteResult
    | GetPromptResult
    | ListPromptsResult
    | ListResourceTemplatesResult
    | ListResourcesResult
    | ReadResourceResult
    | CallToolResult
    | ListToolsResult
)

# ---------- JSONRPC Messages -------------
JSONRPCBatchRequest = list[JSONRPCRequest | JSONRPCNotification]

JSONRPCBatchResponse = list[JSONRPCResponse | JSONRPCError]

JSONRPCMessage = (
    JSONRPCRequest
    | JSONRPCNotification
    | JSONRPCBatchRequest
    | JSONRPCResponse
    | JSONRPCError
    | JSONRPCBatchResponse
)


# ------------ Notification registry -------------

CLIENT_SENT_NOTIFICATION_REGISTRY = {
    "notifications/initialized": InitializedNotification,
    "notifications/cancelled": CancelledNotification,
    "notifications/progress": ProgressNotification,
    "notifications/roots/list_changed": RootsListChangedNotification,
}

SERVER_SENT_NOTIFICATION_REGISTRY = {
    "notifications/cancelled": CancelledNotification,
    "notifications/message": LoggingMessageNotification,
    "notifications/progress": ProgressNotification,
    "notifications/resources/updated": ResourceUpdatedNotification,
    "notifications/resources/list_changed": ResourceListChangedNotification,
    "notifications/tools/list_changed": ToolListChangedNotification,
    "notifications/prompts/list_changed": PromptListChangedNotification,
}

NOTIFICATION_REGISTRY = {
    **CLIENT_SENT_NOTIFICATION_REGISTRY,
    **SERVER_SENT_NOTIFICATION_REGISTRY,
}

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
from conduit.protocol.roots import (
    ListRootsRequest,
    ListRootsResult,
    RootsListChangedNotification,
)
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
    InitializeRequest
    | PingRequest
    | ListToolsRequest
    | CallToolRequest
    | ListResourcesRequest
    | ListResourceTemplatesRequest
    | ReadResourceRequest
    | SubscribeRequest
    | UnsubscribeRequest
    | ListPromptsRequest
    | GetPromptRequest
    | CompleteRequest
    | SetLevelRequest
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
ServerRequest = PingRequest | ListRootsRequest | CreateMessageRequest | ElicitRequest

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

CLIENT_SENT_NOTIFICATION_CLASSES = {
    "notifications/initialized": InitializedNotification,
    "notifications/cancelled": CancelledNotification,
    "notifications/progress": ProgressNotification,
    "notifications/roots/list_changed": RootsListChangedNotification,
}

SERVER_SENT_NOTIFICATION_CLASSES = {
    "notifications/cancelled": CancelledNotification,
    "notifications/message": LoggingMessageNotification,
    "notifications/progress": ProgressNotification,
    "notifications/resources/updated": ResourceUpdatedNotification,
    "notifications/resources/list_changed": ResourceListChangedNotification,
    "notifications/tools/list_changed": ToolListChangedNotification,
    "notifications/prompts/list_changed": PromptListChangedNotification,
}

NOTIFICATION_CLASSES = {
    **CLIENT_SENT_NOTIFICATION_CLASSES,
    **SERVER_SENT_NOTIFICATION_CLASSES,
}

# ------------ Request registry -------------

CLIENT_SENT_REQUEST_CLASSES = {
    "initialize": InitializeRequest,
    "ping": PingRequest,
    "tools/list": ListToolsRequest,
    "tools/call": CallToolRequest,
    "resources/list": ListResourcesRequest,
    "resources/templates/list": ListResourceTemplatesRequest,
    "resources/read": ReadResourceRequest,
    "resources/subscribe": SubscribeRequest,
    "resources/unsubscribe": UnsubscribeRequest,
    "prompts/list": ListPromptsRequest,
    "prompts/get": GetPromptRequest,
    "completion/complete": CompleteRequest,
    "logging/setLevel": SetLevelRequest,
}

SERVER_SENT_REQUEST_CLASSES = {
    "ping": PingRequest,
    "roots/list": ListRootsRequest,
    "sampling/createMessage": CreateMessageRequest,
    "elicitation/create": ElicitRequest,
}

REQUEST_CLASSES = {
    **CLIENT_SENT_REQUEST_CLASSES,
    **SERVER_SENT_REQUEST_CLASSES,
}

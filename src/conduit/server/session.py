from typing import Any, Awaitable, Callable, TypeVar

from conduit.protocol.base import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    Error,
    Request,
    Result,
)
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.completions import CompleteRequest, CompleteResult, Completion
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializeRequest,
    InitializeResult,
    ServerCapabilities,
)
from conduit.protocol.logging import (
    LoggingLevel,
    LoggingMessageNotification,
    SetLevelRequest,
)
from conduit.protocol.prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
    Prompt,
)
from conduit.protocol.resources import (
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    ReadResourceRequest,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    ResourceUpdatedNotification,
    SubscribeRequest,
    UnsubscribeRequest,
)
from conduit.protocol.tools import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    Tool,
)
from conduit.server import utils
from conduit.shared.exceptions import UnknownRequestError
from conduit.shared.session import BaseSession
from conduit.transport.base import Transport

T = TypeVar("T", bound=Request)
RequestHandler = Callable[[T], Awaitable[Result | Error]]
RequestRegistryEntry = tuple[type[T], RequestHandler[T]]


class ServerSession(BaseSession):
    def __init__(
        self,
        transport: Transport,
        server_info: Implementation,
        capabilities: ServerCapabilities,
        instructions: str | None = None,
    ):
        super().__init__(transport)
        self.server_info = server_info
        self.capabilities = capabilities
        self._received_initialized_notification = False
        self._active_subscriptions: set[str] = set()
        self._client_capabilities: ClientCapabilities | None = None
        self.instructions = instructions
        self._current_log_level: LoggingLevel | None = None

        # Tool/prompt/resource registries
        self._registered_tools: dict[str, Tool] = {}
        self._registered_prompts: dict[str, Prompt] = {}
        self._registered_resources: dict[str, Resource] = {}
        self._registered_resource_templates: dict[str, ResourceTemplate] = {}

        # Handlers
        self._resource_handlers: dict[
            str,
            Callable[[ReadResourceRequest], Awaitable[ReadResourceResult]],
        ] = {}
        self._resource_template_handlers: dict[
            str,
            Callable[[ReadResourceRequest], Awaitable[ReadResourceResult]],
        ] = {}
        self._prompt_handlers: dict[
            str,
            Callable[[GetPromptRequest], Awaitable[GetPromptResult]],
        ] = {}
        self._tool_handlers: dict[
            str,
            Callable[[CallToolRequest], Awaitable[CallToolResult]],
        ] = {}
        self._completion_handler: (
            Callable[[CompleteRequest], Awaitable[CompleteResult]] | None
        ) = None
        self._on_log_level_change: Callable[[LoggingLevel], Awaitable[None]] | None = (
            None
        )
        self._on_resource_subscribe: Callable[[str], Awaitable[None]] | None = None
        self._on_resource_unsubscribe: Callable[[str], Awaitable[None]] | None = None

    @property
    def initialized(self) -> bool:
        return self._received_initialized_notification

    def get_client_capabilities(self) -> ClientCapabilities | None:
        return self._client_capabilities

    async def _ensure_can_send_request(self, request: Request) -> None:
        if not self.initialized and not isinstance(request, PingRequest):
            raise RuntimeError(
                "Session must be initialized before sending non-ping requests. "
                "Client must send initialized notification first."
            )

    async def _handle_session_request(self, payload: dict[str, Any]) -> Result | Error:
        method = payload["method"]

        registry = self._get_request_registry()
        if method not in registry:
            raise UnknownRequestError(method)

        request_class, handler = registry[method]
        request = request_class.from_protocol(payload)
        return await handler(request)

    def _get_request_registry(self) -> dict[str, RequestRegistryEntry]:
        return {
            "ping": (PingRequest, self._handle_ping),
            "initialize": (InitializeRequest, self._handle_initialize),
            "tools/list": (ListToolsRequest, self._handle_list_tools),
            "tools/call": (CallToolRequest, self._handle_call_tool),
            "prompts/list": (ListPromptsRequest, self._handle_list_prompts),
            "prompts/get": (GetPromptRequest, self._handle_get_prompt),
            "resources/list": (ListResourcesRequest, self._handle_list_resources),
            "resources/templates/list": (
                ListResourceTemplatesRequest,
                self._handle_list_resource_templates,
            ),
            "resources/read": (ReadResourceRequest, self._handle_read_resource),
            "resources/subscribe": (SubscribeRequest, self._handle_subscribe),
            "resources/unsubscribe": (UnsubscribeRequest, self._handle_unsubscribe),
            "completion/complete": (CompleteRequest, self._handle_complete),
            "logging/setLevel": (SetLevelRequest, self._handle_set_level),
        }

    async def _handle_ping(self, request: PingRequest) -> Result | Error:
        return EmptyResult()

    async def _handle_initialize(self, request: InitializeRequest) -> Result | Error:
        self._client_capabilities = request.capabilities
        return InitializeResult(
            capabilities=self.capabilities,
            server_info=self.server_info,
            instructions=self.instructions,
        )

    async def _handle_list_tools(self, request: ListToolsRequest) -> Result | Error:
        if self.capabilities.tools is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support tools capability",
            )
        return ListToolsResult(tools=list(self._registered_tools.values()))

    async def _handle_list_prompts(self, request: ListPromptsRequest) -> Result | Error:
        if self.capabilities.prompts is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support prompts capability",
            )
        return ListPromptsResult(prompts=list(self._registered_prompts.values()))

    async def _handle_list_resources(
        self, request: ListResourcesRequest
    ) -> Result | Error:
        if self.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        return ListResourcesResult(resources=list(self._registered_resources.values()))

    async def _handle_list_resource_templates(
        self, request: ListResourceTemplatesRequest
    ) -> Result | Error:
        if self.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        return ListResourceTemplatesResult(
            resource_templates=list(self._registered_resource_templates.values())
        )

    async def _handle_read_resource(
        self, request: ReadResourceRequest
    ) -> Result | Error:
        if self.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )

        uri = str(request.uri)
        if uri in self._resource_handlers:
            return await self._resource_handlers[uri](request)

        for template_pattern, handler in self._resource_template_handlers.items():
            if utils.matches_template(template_pattern, uri):
                return await handler(request)

        return Error(code=METHOD_NOT_FOUND, message=f"Unknown resource: {uri}")

    async def _handle_get_prompt(self, request: GetPromptRequest) -> Result | Error:
        if self.capabilities.prompts is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support prompts capability",
            )

        name = str(request.name)
        if name not in self._prompt_handlers:
            return Error(
                code=METHOD_NOT_FOUND,
                message=f"Unknown prompt: {name}",
            )

        return await self._prompt_handlers[name](request)

    async def _handle_call_tool(self, request: CallToolRequest) -> Result | Error:
        if self.capabilities.tools is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support tools capability",
            )

        name = str(request.name)
        if name not in self._tool_handlers:
            return Error(
                code=METHOD_NOT_FOUND,
                message=f"Unknown tool: {name}",
            )

        return await self._tool_handlers[name](request)

    async def _handle_complete(self, request: CompleteRequest) -> Result | Error:
        if self.capabilities.completions is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support completion capability",
            )

        if self._completion_handler:
            return await self._completion_handler(request)

        return CompleteResult(completion=Completion(values=[]))

    async def _handle_set_level(self, request: SetLevelRequest) -> Result | Error:
        if self.capabilities.logging is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support logging capability",
            )

        self._current_log_level = request.level

        if self._on_log_level_change:
            try:
                await self._on_log_level_change(request.level)
            except Exception:
                return Error(
                    code=INTERNAL_ERROR,
                    message="Error in log level change callback",
                )

        return EmptyResult()

    async def _handle_subscribe(self, request: SubscribeRequest) -> Result | Error:
        if self.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )

        uri = str(request.uri)
        if uri not in self._registered_resources:
            # try template matching
            template_found = False
            for template_pattern in self._registered_resource_templates.keys():
                if utils.matches_template(uri=uri, template=template_pattern):
                    template_found = True
                    break

            if not template_found:
                return Error(
                    code=METHOD_NOT_FOUND,
                    message=f"Cannot subscribe to unknown resource: {uri}",
                )
        self._active_subscriptions.add(uri)
        if self._on_resource_subscribe:
            try:
                await self._on_resource_subscribe(uri)
            except Exception:
                return Error(
                    code=INTERNAL_ERROR,
                    message="Error in resource subscribe handler",
                )

        return EmptyResult()

    async def _handle_unsubscribe(self, request: UnsubscribeRequest) -> Result | Error:
        if self.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )

        uri = str(request.uri)
        if uri not in self._active_subscriptions:
            return Error(
                code=METHOD_NOT_FOUND,
                message=f"Cannot unsubscribe from unknown resource: {uri}",
            )

        self._active_subscriptions.discard(uri)
        if self._on_resource_unsubscribe:
            try:
                await self._on_resource_unsubscribe(uri)
            except Exception:
                return Error(
                    code=INTERNAL_ERROR,
                    message="Error in resource unsubscribe handler",
                )

        return EmptyResult()

    def _should_send_log(self, level: LoggingLevel) -> bool:
        """Check if a log message should be sent based on current log level."""
        if self._current_log_level is None:
            return False

        priorities = {
            "debug": 0,
            "info": 1,
            "notice": 2,
            "warning": 3,
            "error": 4,
            "critical": 5,
            "alert": 6,
            "emergency": 7,
        }

        current_priority = priorities.get(self._current_log_level, 0)
        message_priority = priorities.get(level, 0)

        return message_priority >= current_priority

    def register_resource(
        self,
        resource: Resource,
        handler: Callable[[ReadResourceRequest], Awaitable[ReadResourceResult]],
    ) -> None:
        """Register resource metadata and handler together."""
        uri = str(resource.uri)
        self._registered_resources[uri] = resource
        self._resource_handlers[uri] = handler

    def register_resource_template(
        self,
        template: ResourceTemplate,
        handler: Callable[[ReadResourceRequest], Awaitable[ReadResourceResult]],
    ) -> None:
        """Register resource template metadata and handler together."""
        self._registered_resource_templates[template.name] = template
        self._resource_template_handlers[template.uri_template] = handler

    def register_prompt(
        self,
        prompt: Prompt,
        handler: Callable[[GetPromptRequest], Awaitable[GetPromptResult]],
    ) -> None:
        """Register prompt metadata and handler together."""
        name = str(prompt.name)
        self._registered_prompts[name] = prompt
        self._prompt_handlers[name] = handler

    def register_tool(
        self,
        tool: Tool,
        handler: Callable[[CallToolRequest], Awaitable[CallToolResult]],
    ) -> None:
        """Register tool metadata and handler together."""
        name = tool.name
        self._registered_tools[name] = tool
        self._tool_handlers[name] = handler

    def set_completion_handler(
        self,
        handler: Callable[[CompleteRequest], Awaitable[CompleteResult]],
    ) -> None:
        """Set custom completion handler for all completion requests."""
        self._completion_handler = handler

    def on_log_level_change(
        self,
        handler: Callable[[LoggingLevel], Awaitable[None]],
    ) -> None:
        """Set custom log level change handler."""
        self._on_log_level_change = handler

    def on_resource_subscribe(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """Set callback for resource subscription events."""
        self._on_resource_subscribe = callback

    def on_resource_unsubscribe(
        self, callback: Callable[[str], Awaitable[None]]
    ) -> None:
        """Set callback for resource unsubscription events."""
        self._on_resource_unsubscribe = callback

    async def send_resource_updated(self, uri: str) -> None:
        """Send resource updated notification if client is subscribed."""
        if uri in self._active_subscriptions:
            notification = ResourceUpdatedNotification(uri=uri)
            await self.send_notification(notification)

    async def send_logging_notification(
        self, level: LoggingLevel, data: Any, logger: str | None = None
    ) -> None:
        """Send logging notification if client is subscribed."""
        if self._should_send_log(level):
            notification = LoggingMessageNotification(
                level=level, data=data, logger=logger
            )
            await self.send_notification(notification)

from dataclasses import dataclass

from conduit.protocol.base import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    Error,
    Notification,
    Request,
    Result,
)
from conduit.protocol.common import (
    CancelledNotification,
    EmptyResult,
    PingRequest,
    ProgressNotification,
)
from conduit.protocol.completions import CompleteRequest, CompleteResult
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
    ServerCapabilities,
)
from conduit.protocol.logging import (
    SetLevelRequest,
)
from conduit.protocol.prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
)
from conduit.protocol.resources import (
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    ReadResourceRequest,
    ReadResourceResult,
    SubscribeRequest,
    UnsubscribeRequest,
)
from conduit.protocol.roots import (
    ListRootsRequest,
    ListRootsResult,
    Root,
    RootsListChangedNotification,
)
from conduit.protocol.tools import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
)
from conduit.server.managers.callbacks import CallbackManager
from conduit.server.managers.completions import (
    CompletionManager,
    CompletionNotConfiguredError,
)
from conduit.server.managers.logging import LoggingManager
from conduit.server.managers.prompts import PromptManager
from conduit.server.managers.resources import ResourceManager
from conduit.server.managers.tools import ToolManager
from conduit.shared.session import BaseSession
from conduit.transport.base import Transport


@dataclass
class ServerConfig:
    capabilities: ServerCapabilities
    info: Implementation
    instructions: str | None = None
    protocol_version: str = PROTOCOL_VERSION


@dataclass
class ClientState:
    capabilities: ClientCapabilities | None = None
    info: Implementation | None = None
    protocol_version: str | None = None

    # Domain state
    roots: list[Root] | None = None


class ServerSession(BaseSession):
    def __init__(
        self,
        transport: Transport,
        config: ServerConfig,
    ):
        super().__init__(transport)
        self.server_config = config
        self.client_state = ClientState()
        self._received_initialized: bool = False

        # Domain managers
        self.tools = ToolManager()
        self.resources = ResourceManager()
        self.prompts = PromptManager()
        self.logging = LoggingManager()
        self.completions = CompletionManager()
        self.callbacks = CallbackManager()

    # ================================
    # Initialization
    # ================================
    @property
    def initialized(self) -> bool:
        return self._received_initialized

    async def _handle_initialize(
        self, request: InitializeRequest
    ) -> InitializeResult | Error:
        """Handle client initialization request.

        Stores client capabilities and info for the session, then responds with
        server capabilities to continue the initialization handshake.

        Args:
            request: The client's initialization request containing capabilities,
                version, and implementation details.

        Returns:
            InitializeResult: The server's response containing its capabilities,
                version, and instructions for the client.
        """
        self._store_client_state(request)
        return InitializeResult(
            capabilities=self.server_config.capabilities,
            server_info=self.server_config.info,
            protocol_version=self.server_config.protocol_version,
            instructions=self.server_config.instructions,
        )

    async def _handle_initialized(self, notification: InitializedNotification) -> None:
        """Complete the initialization handshake.

        Marks the server as fully initialized and notifies any registered callbacks.
        After this point, the session is ready for normal operation.

        Args:
            notification: Confirmation from the client that initialization completed.
        """
        self._received_initialized = True
        await self.callbacks.call_initialized()

    def _store_client_state(self, request: InitializeRequest) -> None:
        """Store client information from initialization request.

        Captures the client's capabilities, version, and implementation details
        for use throughout the session. This information helps the server adapt
        its behavior based on what the client supports.

        Args:
            request: The client's initialization request containing capabilities,
                version, and implementation details.
        """
        self.client_state.capabilities = request.capabilities
        self.client_state.info = request.client_info
        self.client_state.protocol_version = request.protocol_version

    # ================================
    # Request routing
    # ================================

    async def _handle_session_request(self, request: Request) -> Result | Error:
        """Route incoming requests to the appropriate handler.

        Returns an error if there is no handler for the request type.

        Args:
            request: Typed Request object from the base session.

        Returns:
            Result from the handler, or Error if handler returns one.

        Note:
            Handlers are responsible for capability checking and returning
            appropriate Error objects rather than raising exceptions.
        """
        method = request.method

        handlers = self._get_request_handlers()
        if method not in handlers:
            return Error(
                code=METHOD_NOT_FOUND, message=f"Method not supported: {method}"
            )

        handler = handlers[method]
        return await handler(request)

    def _get_request_handlers(self):
        """Get the request handlers for the server session.

        Maps request methods to their corresponding handler functions.
        """
        return {
            "ping": self._handle_ping,
            "initialize": self._handle_initialize,
            "tools/list": self._handle_list_tools,
            "tools/call": self._handle_call_tool,
            "prompts/list": self._handle_list_prompts,
            "prompts/get": self._handle_get_prompt,
            "resources/list": self._handle_list_resources,
            "resources/templates/list": self._handle_list_resource_templates,
            "resources/read": self._handle_read_resource,
            "resources/subscribe": self._handle_subscribe,
            "resources/unsubscribe": self._handle_unsubscribe,
            "completion/complete": self._handle_complete,
            "logging/setLevel": self._handle_set_level,
        }

    # ================================
    # Ping
    # ================================

    async def _handle_ping(self, request: PingRequest) -> EmptyResult:
        return EmptyResult()

    # ================================
    # Tools
    # ================================

    async def _handle_list_tools(
        self, request: ListToolsRequest
    ) -> ListToolsResult | Error:
        """Handle a tools discovery request.

        Enables clients to discover what capabilities this server offers.

        Args:
            request: The client's tool listing request.

        Returns:
            ListToolsResult: The server's catalog of available tools.
            Error: If the server does not support the tools capability.
        """
        if self.server_config.capabilities.tools is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support tools capability",
            )
        return await self.tools.handle_list(request)

    async def _handle_call_tool(
        self, request: CallToolRequest
    ) -> CallToolResult | Error:
        """Execute a tool call request.

        Tool execution failures become domain errors (CallToolResult with
        is_error=True) that the LLM can see and potentially recover from.
        System errors like unknown tools or missing capabilities return
        protocol errors.

        Args:
            request: Tool call request with name and arguments.

        Returns:
            CallToolResult: Tool output, even if execution failed.
            Error: If tools capability not supported or tool unknown.
        """
        if self.server_config.capabilities.tools is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support tools capability",
            )
        try:
            return await self.tools.handle_call(request)
        except KeyError:
            return Error(code=METHOD_NOT_FOUND, message=f"Unknown tool: {request.name}")

    # ================================
    # Prompts
    # ================================

    async def _handle_list_prompts(
        self, request: ListPromptsRequest
    ) -> ListPromptsResult | Error:
        """List available prompts.

        Args:
            request: List prompts request with optional pagination.

        Returns:
            ListPromptsResult: List of available prompts.
            Error: If prompts capability not supported.
        """
        if self.server_config.capabilities.prompts is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support prompts capability",
            )
        return await self.prompts.handle_list_prompts(request)

    async def _handle_get_prompt(
        self, request: GetPromptRequest
    ) -> GetPromptResult | Error:
        """Retrieve a specific prompt with the given arguments.

        The manager handles prompt execution and raises exceptions for unknown
        prompts or handler failures. We convert these to appropriate protocol
        errors.

        Args:
            request: Get prompt request with name and arguments.

        Returns:
            GetPromptResult: Prompt messages and metadata.
            Error: If prompts capability not supported, prompt unknown, or handler
                fails.
        """
        if self.server_config.capabilities.prompts is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support prompts capability",
            )
        try:
            return await self.prompts.handle_get_prompt(request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Error in prompt handler",
            )

    # ================================
    # Resources
    # ================================

    async def _handle_list_resources(
        self, request: ListResourcesRequest
    ) -> ListResourcesResult | Error:
        """List available resources.

        Args:
            request: List resources request with optional pagination.

        Returns:
            ListResourcesResult: List of available resources.
            Error: If resources capability not supported.
        """
        if self.server_config.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        return await self.resources.handle_list_resources(request)

    async def _handle_list_resource_templates(
        self, request: ListResourceTemplatesRequest
    ) -> ListResourceTemplatesResult | Error:
        """List available resource templates.

        Args:
            request: List templates request with optional pagination.

        Returns:
            ListResourceTemplatesResult: List of available resource templates.
            Error: If resources capability not supported.
        """
        if self.server_config.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        return await self.resources.handle_list_templates(request)

    async def _handle_read_resource(
        self, request: ReadResourceRequest
    ) -> ReadResourceResult | Error:
        """Read a specific resource by URI.

        The manager handles both static resources and template pattern matching.
        It raises exceptions for unknown resources or handler failures that we
        convert to appropriate protocol errors.

        Args:
            request: Read resource request with URI.

        Returns:
            ReadResourceResult: Resource content from the handler.
            Error: If resources capability not supported, resource unknown, or
                handler fails.
        """
        if self.server_config.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        try:
            return await self.resources.handle_read(request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Error reading resource",
            )

    async def _handle_subscribe(self, request: SubscribeRequest) -> EmptyResult | Error:
        """Subscribe to resource change notifications.

        Requires both resources capability and subscribe sub-capability to be enabled.
        The manager validates resource existence and handles callback failures
        internally.

        Args:
            request: Subscribe request with resource URI.

        Returns:
            EmptyResult: Subscription successful.
            Error: If subscription capability not supported or resource unknown.
        """
        if not (
            self.server_config.capabilities.resources
            and self.server_config.capabilities.resources.subscribe
        ):
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resource subscription",
            )

        try:
            return await self.resources.handle_subscribe(request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))

    async def _handle_unsubscribe(
        self, request: UnsubscribeRequest
    ) -> EmptyResult | Error:
        """Unsubscribe from resource change notifications.

        Requires both resources capability and subscribe sub-capability to be enabled.
        The manager validates subscription existence and handles callback failures
        internally.

        Args:
            request: Unsubscribe request with resource URI.

        Returns:
            EmptyResult: Unsubscription successful.
            Error: If subscription capability not supported or not subscribed to
                resource.
        """
        if not (
            self.server_config.capabilities.resources
            and self.server_config.capabilities.resources.subscribe
        ):
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resource subscription",
            )
        try:
            return await self.resources.handle_unsubscribe(request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))

    # ================================
    # Completions
    # ================================

    async def _handle_complete(
        self, request: CompleteRequest
    ) -> CompleteResult | Error:
        """Generate completions for prompts or resource templates.

        The manager validates that a completion handler is configured and delegates
        to it for generation. Handler exceptions become internal errors.

        Args:
            request: Complete request with reference and arguments.

        Returns:
            CompleteResult: Generated completion from the handler.
            Error: If completions capability not supported, handler not configured,
                or generation fails.
        """
        if not self.server_config.capabilities.completions:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support completion capability",
            )

        try:
            return await self.completions.handle_complete(request)
        except CompletionNotConfiguredError:
            return Error(
                code=METHOD_NOT_FOUND,
                message="No completion handler registered.",
            )
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Error generating completions.",
            )

    # ================================
    # Logging
    # ================================

    async def _handle_set_level(self, request: SetLevelRequest) -> EmptyResult | Error:
        """Set the MCP protocol logging level.

        The manager handles level setting and callback notifications internally.
        Callback failures don't cause protocol errors since the level is successfully
        set.

        Args:
            request: Set level request with the new logging level.

        Returns:
            EmptyResult: Level set successfully.
            Error: If logging capability not supported.
        """
        if not self.server_config.capabilities.logging:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support logging capability",
            )

        return await self.logging.handle_set_level(request)

    # ================================
    # Notification handlers
    # ================================

    async def _handle_session_notification(self, notification: Notification) -> None:
        """Route incoming notifications to the appropriate handler.

        Args:
            notification: Typed Notification object from the base session.

        Note:
            Only notifications with registered handlers are processed. Unknown
            notification types are ignored, but missing handlers are silently ignored.
        """
        method = notification.method
        handlers = self._get_notification_handlers()

        if method in handlers:
            handler = handlers[method]
            await handler(notification)
        # Silently ignore notifications without handlers

    def _get_notification_handlers(self):
        return {
            "notifications/cancelled": self._handle_cancelled,
            "notifications/progress": self._handle_progress,
            "notifications/roots/list_changed": self._handle_roots_list_changed,
            "notifications/initialized": self._handle_initialized,
        }

    async def _handle_cancelled(self, notification: CancelledNotification) -> None:
        """Handle client cancellation notifications for in-flight requests.

        Cancels the corresponding request task if it exists and calls the
        registered callback. Only processes cancellations for requests that
        are actually in-flight.

        Args:
            notification: Cancellation notification from server with request ID.

        Note:
            Request cleanup from _in_flight_requests is handled automatically
            by the task's done callback when cancellation completes. This handler
            only initiates cancellation and calls the registered callback.
        """
        if notification.request_id in self._in_flight_requests:
            self._in_flight_requests[notification.request_id].cancel()
            await self.callbacks.call_cancelled(notification)

    async def _handle_progress(self, notification: ProgressNotification) -> None:
        """Handle client progress notifications.

        Delegates progress updates to the callback manager.

        Args:
            notification: Progress notification from server with progress token.
        """
        await self.callbacks.call_progress(notification)

    async def _handle_roots_list_changed(
        self, notification: RootsListChangedNotification
    ) -> None:
        """Handle client roots list changed notifications.

        Fetches the updated roots list from the server, updates local client
        state, and calls the registered callback with the new roots.

        Args:
            notification: Notification that roots have changed (content ignored).
        """
        try:
            result = await self.send_request(ListRootsRequest())
            if isinstance(result, ListRootsResult):
                self.client_state.roots = result.roots
                await self.callbacks.call_roots_changed(result.roots)
        except Exception:
            pass

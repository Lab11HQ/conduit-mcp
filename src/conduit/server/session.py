"""MCP server session for handling client protocol conversations.

The ServerSession class implements MCP protocol handlers for client requests
and notifications, then registers them with a message coordinator to handle
the full protocol lifecycle.
"""

import logging
import sys
from dataclasses import dataclass

from conduit.protocol.base import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_MISMATCH,
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
    PROTOCOL_VERSION,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
    ServerCapabilities,
)
from conduit.protocol.logging import SetLevelRequest
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
    RootsListChangedNotification,
)
from conduit.protocol.tools import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
)
from conduit.server.callbacks import CallbackManager
from conduit.server.client_manager import ClientManager
from conduit.server.coordinator import MessageCoordinator
from conduit.server.protocol.completions import (
    CompletionManager,
    CompletionNotConfiguredError,
)
from conduit.server.protocol.logging import LoggingManager
from conduit.server.protocol.prompts import PromptManager
from conduit.server.protocol.resources import ResourceManager
from conduit.server.protocol.tools import ToolManager
from conduit.server.request_context import RequestContext
from conduit.transport.server import ServerTransport


@dataclass
class ServerConfig:
    capabilities: ServerCapabilities
    info: Implementation
    instructions: str | None = None
    protocol_version: str = PROTOCOL_VERSION


class ServerSession:
    """MCP server session handling protocol conversations with clients."""

    def __init__(self, transport: ServerTransport, config: ServerConfig):
        """Initialize the server session.

        Registers all protocol handlers with the message processor.

        Args:
            transport: The transport layer to use for client connections
                (e.g., stdio, streamable HTTP, etc.)
            config: The server configuration
        """

        # Transport and config
        self.transport = transport
        self.server_config = config

        # Client manager
        self.client_manager = ClientManager()

        # Domain managers
        self.tools = ToolManager()
        self.resources = ResourceManager()
        self.prompts = PromptManager()
        self.logging = LoggingManager()
        self.completions = CompletionManager()
        self.callbacks = CallbackManager()

        # Coordinator
        self._coordinator = MessageCoordinator(transport, self.client_manager)

        # Configure logging if not already configured
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                stream=sys.stderr,
            )
        self.logger = logging.getLogger("conduit.server.session")

        # Register handlers
        self._register_handlers()

    # ================================
    # Lifecycle
    # ================================

    async def _start(self) -> None:
        """Start accepting and processing client messages.

        Starts the background message loop that will handle incoming client
        messages and route them to the appropriate handlers.
        """
        await self._coordinator.start()

    async def _stop(self) -> None:
        """Stop listening for client messages."""
        await self._coordinator.stop()

    async def _cleanup_client(self, client_id: str) -> None:
        """Clean up all state for a specific client."""

        # Clean up domain managers
        self.tools.cleanup_client(client_id)
        self.resources.cleanup_client(client_id)
        self.prompts.cleanup_client(client_id)
        self.logging.cleanup_client(client_id)

        # Clean up client manager
        self.client_manager.cleanup_client(client_id)

    async def disconnect_client(self, client_id: str) -> None:
        """Disconnect a client and clean up all state."""
        await self._cleanup_client(client_id)
        try:
            await self.transport.disconnect_client(client_id)
        except Exception as e:
            self.logger.warning(
                f"Transport error while disconnecting from client {client_id}: {e}"
            )

    async def disconnect_all_clients(self) -> None:
        """Disconnect all clients and clean up all state."""
        await self._stop()
        for client_id in self.client_manager.get_client_ids():
            await self.disconnect_client(client_id)

    # ================================
    # Initialization
    # ================================

    async def _handle_initialize(
        self, context: RequestContext, request: InitializeRequest
    ) -> InitializeResult | Error:
        """Handle the first step of the MCP initialization handshake.

        Validates protocol version compatibility and stores the client's
        capabilities and info. Returns the server's capabilities and
        configuration so the client knows what features are available.

        Client must send an 'initialized' notification to complete the process.

        Returns:
            InitializeResult: The server's capabilities and configuration.
            Error: If the protocol version is incompatible or the client is already
                initialized.
        """
        client_id = context.client_id
        if request.protocol_version != self.server_config.protocol_version:
            return Error(
                code=PROTOCOL_VERSION_MISMATCH,
                message="Unsupported protocol version",
                data={
                    "client_version": request.protocol_version,
                    "server_version": self.server_config.protocol_version,
                },
            )

        # Check if client is already initialized
        if self.client_manager.is_protocol_initialized(client_id):
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client already initialized",
            )

        self.client_manager.initialize_client(
            client_id,
            capabilities=request.capabilities,
            client_info=request.client_info,
            protocol_version=request.protocol_version,
        )
        # Session focuses on protocol response
        return InitializeResult(
            capabilities=self.server_config.capabilities,
            server_info=self.server_config.info,
            protocol_version=self.server_config.protocol_version,
            instructions=self.server_config.instructions,
        )

    async def _handle_initialized(
        self, context: RequestContext, notification: InitializedNotification
    ) -> None:
        """Complete the initialization handshake.

        Marks the client as fully initialized and calls any registered callbacks.
        After this point, the client is ready for normal operation.
        """
        client_id = context.client_id
        state = self.client_manager.get_client(client_id)
        if state:
            state.initialized = True

        await self.callbacks.call_initialized(client_id, notification)

    # ================================
    # Ping
    # ================================

    async def _handle_ping(
        self, context: RequestContext, request: PingRequest
    ) -> EmptyResult:
        """Always returns an empty result.

        Clients send pings to check connection health.
        """
        return EmptyResult()

    # ================================
    # Tools
    # ================================

    async def _handle_list_tools(
        self, context: RequestContext, request: ListToolsRequest
    ) -> ListToolsResult | Error:
        """Returns the list of available tools.

        Returns:
            ListToolsResult: The available tools and their metadata.
            Error: If the server doesn't support the tools capability.
        """
        if self.server_config.capabilities.tools is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support tools capability",
            )

        return await self.tools.handle_list(context, request)

    async def _handle_call_tool(
        self, context: RequestContext, request: CallToolRequest
    ) -> CallToolResult | Error:
        """Executes a tool call.

        Tool execution failures are returned as CallToolResult with is_error=True,
        allowing the LLM to see what went wrong and potentially recover.

        Returns:
            CallToolResult: Tool output or execution error details.
            Error: If the server doesn't support tools or the tool doesn't exist.
        """
        if self.server_config.capabilities.tools is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support tools capability",
            )
        try:
            return await self.tools.handle_call(context, request)
        except KeyError:
            return Error(code=METHOD_NOT_FOUND, message=f"Unknown tool: {request.name}")

    # ================================
    # Prompts
    # ================================

    async def _handle_list_prompts(
        self, context: RequestContext, request: ListPromptsRequest
    ) -> ListPromptsResult | Error:
        """Returns the list of available prompts.

        Returns:
            ListPromptsResult: The available prompts and their metadata.
            Error: If the server doesn't support the prompts capability.
        """
        if self.server_config.capabilities.prompts is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support prompts capability",
            )
        return await self.prompts.handle_list_prompts(context, request)

    async def _handle_get_prompt(
        self, context: RequestContext, request: GetPromptRequest
    ) -> GetPromptResult | Error:
        """Returns the contents of a specific prompt.

        Returns:
            GetPromptResult: The contents of the prompt.
            Error: If the server doesn't support the prompts capability, the prompt
                doesn't exist, or there's an error retrieving the prompt.
        """
        if self.server_config.capabilities.prompts is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support prompts capability",
            )
        try:
            return await self.prompts.handle_get_prompt(context, request)
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
        self, context: RequestContext, request: ListResourcesRequest
    ) -> ListResourcesResult | Error:
        """Returns the list of available resources.

        Returns:
            ListResourcesResult: The available resources.
            Error: If the server doesn't support the resources capability.
        """
        if self.server_config.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )

        return await self.resources.handle_list_resources(context, request)

    async def _handle_list_resource_templates(
        self, context: RequestContext, request: ListResourceTemplatesRequest
    ) -> ListResourceTemplatesResult | Error:
        """Returns the list of available resource templates.

        Returns:
            ListResourceTemplatesResult: The available resource templates.
            Error: If the server doesn't support the resources capability.
        """
        if self.server_config.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        return await self.resources.handle_list_templates(context, request)

    async def _handle_read_resource(
        self, context: RequestContext, request: ReadResourceRequest
    ) -> ReadResourceResult | Error:
        """Returns the contents of a specific resource.

        Returns:
            ReadResourceResult: The contents of the resource.
            Error: If the server doesn't support the resources capability, the resource
                doesn't exist, or there's an error reading the resource.
        """
        if self.server_config.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        try:
            return await self.resources.handle_read(context, request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Error reading resource",
            )

    async def _handle_subscribe(
        self, context: RequestContext, request: SubscribeRequest
    ) -> EmptyResult | Error:
        """Subscribes a client to a resource.

        Returns:
            EmptyResult: Successfully subscribed to the resource.
            Error: If the server doesn't support subscription or the resource
                doesn't exist.
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
            return await self.resources.handle_subscribe(context, request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))

    async def _handle_unsubscribe(
        self, context: RequestContext, request: UnsubscribeRequest
    ) -> EmptyResult | Error:
        """Unsubscribes a client from a resource.

        Returns:
            EmptyResult: Successfully unsubscribed from the resource.
            Error: If the server doesn't support unsubscription or the client
                is not subscribed to the resource.
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
            return await self.resources.handle_unsubscribe(context, request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))

    # ================================
    # Completions
    # ================================

    async def _handle_complete(
        self, context: RequestContext, request: CompleteRequest
    ) -> CompleteResult | Error:
        """Generates a completion for a given prompt.

        Returns:
            CompleteResult: The completion.
            Error: If the server doesn't support completions or there's an error
                generating the completion.
        """
        if not self.server_config.capabilities.completions:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support completions capability",
            )
        try:
            return await self.completions.handle_complete(context, request)
        except CompletionNotConfiguredError:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Completion handler not configured",
            )
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Error generating completions.",
            )

    # ================================
    # Logging
    # ================================

    async def _handle_set_level(
        self, context: RequestContext, request: SetLevelRequest
    ) -> EmptyResult | Error:
        """Sets the logging level for the given client.

        Returns:
            EmptyResult: Successfully set the logging level.
            Error: If the server doesn't support logging or there's an error
                setting the logging level.
        """
        if not self.server_config.capabilities.logging:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support logging capability",
            )
        return await self.logging.handle_set_level(context, request)

    # ================================
    # Notifications
    # ================================

    async def _handle_cancelled(
        self, context: RequestContext, notification: CancelledNotification
    ) -> None:
        """Cancels a request from a client and calls the registered callback."""
        client_id = context.client_id
        await self._coordinator.cancel_request_from_client(
            client_id, notification.request_id
        )
        await self.callbacks.call_cancelled(client_id, notification)

    async def _handle_progress(
        self, context: RequestContext, notification: ProgressNotification
    ) -> None:
        """Calls the registered callback for progress updates."""
        client_id = context.client_id
        await self.callbacks.call_progress(client_id, notification)

    async def _handle_roots_list_changed(
        self, context: RequestContext, notification: RootsListChangedNotification
    ) -> None:
        """Handles roots/list_changed notification.

        Fetch the updated list of roots from the client, update the client state,
        and call any registered callbacks.
        """
        client_id = context.client_id
        try:
            result = await self.send_request(client_id, ListRootsRequest())

            if isinstance(result, ListRootsResult):
                state = self.client_manager.get_client(client_id)
                if state:
                    state.roots = result.roots

                await self.callbacks.call_roots_changed(client_id, result.roots)
            else:
                self.logger.error(f"Failed to get roots from {client_id}: {result}")

        except Exception as e:
            self.logger.error(f"Error handling roots change for {client_id}: {e}")

    # ================================
    # Send messages
    # ================================

    async def send_request(
        self, client_id: str, request: Request, timeout: float = 30.0
    ) -> Result | Error:
        """Send a request to a client.

        Ensures that the client has completed MCP initialization before sending
        non-ping requests.

        Args:
            client_id: ID of the client to send the request to
            request: The request object to send
            timeout: Maximum time to wait for response in seconds (default 30s)

        Returns:
            Result | Error: The client's response or timeout error

        Raises:
            ValueError: If attempting to send non-ping request to uninitialized client
            ConnectionError: If transport is closed
            TimeoutError: If client doesn't respond within timeout
        """
        await self._start()
        if request.method != "ping" and not self.client_manager.is_protocol_initialized(
            client_id
        ):
            raise ValueError(
                f"Cannot send {request.method} to client {client_id}. "
                "Client must complete MCP protocol initialization first."
            )

        return await self._coordinator.send_request(client_id, request, timeout)

    async def send_notification(
        self, client_id: str, notification: Notification
    ) -> None:
        """Send a notification to a client.

        Args:
            client_id: ID of the client to send the notification to
            notification: The notification object to send

        Raises:
            ConnectionError: If transport is closed
        """
        await self._start()
        await self._coordinator.send_notification(client_id, notification)

    # ================================
    # Register handlers
    # ================================

    def _register_handlers(self) -> None:
        """Register all protocol handlers with the message processor."""
        # Request handlers
        self._coordinator.register_request_handler("ping", self._handle_ping)
        self._coordinator.register_request_handler(
            "initialize", self._handle_initialize
        )
        self._coordinator.register_request_handler(
            "tools/list", self._handle_list_tools
        )
        self._coordinator.register_request_handler("tools/call", self._handle_call_tool)
        self._coordinator.register_request_handler(
            "prompts/list", self._handle_list_prompts
        )
        self._coordinator.register_request_handler(
            "prompts/get", self._handle_get_prompt
        )
        self._coordinator.register_request_handler(
            "resources/list", self._handle_list_resources
        )
        self._coordinator.register_request_handler(
            "resources/templates/list", self._handle_list_resource_templates
        )
        self._coordinator.register_request_handler(
            "resources/read", self._handle_read_resource
        )
        self._coordinator.register_request_handler(
            "resources/subscribe", self._handle_subscribe
        )
        self._coordinator.register_request_handler(
            "resources/unsubscribe", self._handle_unsubscribe
        )
        self._coordinator.register_request_handler(
            "completion/complete", self._handle_complete
        )
        self._coordinator.register_request_handler(
            "logging/setLevel", self._handle_set_level
        )

        # Notification handlers
        self._coordinator.register_notification_handler(
            "notifications/cancelled", self._handle_cancelled
        )
        self._coordinator.register_notification_handler(
            "notifications/progress", self._handle_progress
        )
        self._coordinator.register_notification_handler(
            "notifications/roots/list_changed", self._handle_roots_list_changed
        )
        self._coordinator.register_notification_handler(
            "notifications/initialized", self._handle_initialized
        )

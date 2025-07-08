"""Multi-client aware server session implementation."""

from dataclasses import dataclass

from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND, Error
from conduit.protocol.common import (
    CancelledNotification,
    EmptyResult,
    PingRequest,
    ProgressNotification,
)
from conduit.protocol.completions import CompleteRequest, CompleteResult
from conduit.protocol.initialization import (
    PROTOCOL_VERSION,
    ClientCapabilities,
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
from conduit.protocol.roots import Root, RootsListChangedNotification
from conduit.protocol.tools import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
)
from conduit.server.coordinator import MessageCoordinator
from conduit.server.managers.callbacks_v2 import CallbackManager
from conduit.server.managers.completions_v2 import (
    CompletionManager,
    CompletionNotConfiguredError,
)
from conduit.server.managers.logging_v2 import LoggingManager
from conduit.server.managers.prompts_v2 import PromptManager
from conduit.server.managers.resources_v2 import ResourceManager
from conduit.server.managers.tools_v2 import ToolManager
from conduit.transport.server import ServerTransport


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


class ServerSession:
    """Multi-client aware MCP server session.

    Handles protocol logic for multiple clients simultaneously, with each
    client maintaining its own state and initialization status. Uses a
    MessageProcessor to handle message loop mechanics while focusing on
    protocol implementation.
    """

    def __init__(self, transport: ServerTransport, config: ServerConfig):
        self.transport = transport
        self.server_config = config

        # Multi-client state management
        self.clients: dict[str, ClientState] = {}
        self.initialized_clients: set[str] = set()

        # Domain managers (these will need client-aware updates)
        self.tools = ToolManager()
        self.resources = ResourceManager()
        self.prompts = PromptManager()
        self.logging = LoggingManager()
        self.completions = CompletionManager()
        self.callbacks = CallbackManager()

        # Message processing
        self._coordinator = MessageCoordinator(transport)
        self._register_handlers()

    async def start(self) -> None:
        """Start the server session and message processing."""
        await self._coordinator.start()

    async def stop(self) -> None:
        """Stop the server session and clean up client connections."""
        await self._coordinator.stop()
        self.clients.clear()
        self.initialized_clients.clear()

    # ================================
    # Initialization
    # ================================
    @property
    def initialized(self) -> bool:
        """True if at least one client is initialized."""
        return len(self.initialized_clients) > 0

    def is_client_initialized(self, client_id: str) -> bool:
        """Check if a specific client is initialized."""
        return client_id in self.initialized_clients

    async def _handle_initialize(
        self, client_id: str, request: InitializeRequest
    ) -> InitializeResult | Error:
        """Handle initialize request from specific client."""
        # TODO: Store client state, mark as initialized, return result
        pass

    async def _handle_initialized(
        self, client_id: str, notification: InitializedNotification
    ) -> None:
        """Handle initialized notification from specific client."""
        # TODO: Mark client as initialized
        pass

    def _ensure_client_exists(self, client_id: str) -> None:
        """Ensure client state exists for the given client ID."""
        if client_id not in self.clients:
            self.clients[client_id] = ClientState()

    def _store_client_state(self, client_id: str, request: InitializeRequest) -> None:
        """Store client information from initialization request.

        Args:
            client_id: The client's unique identifier
            request: The client's initialization request containing capabilities
        """
        self._ensure_client_exists(client_id)
        client_state = self.clients[client_id]
        client_state.capabilities = request.capabilities
        client_state.info = request.client_info
        client_state.protocol_version = request.protocol_version

    # ================================
    # Ping
    # ================================

    async def _handle_ping(self, client_id: str, request: PingRequest) -> EmptyResult:
        """Handle ping request from specific client."""
        return EmptyResult()

    # ================================
    # Tools
    # ================================

    async def _handle_list_tools(
        self, client_id: str, request: ListToolsRequest
    ) -> ListToolsResult | Error:
        """Handle typed tools/list request - much cleaner!"""
        if self.server_config.capabilities.tools is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support tools capability",
            )

        return await self.tools.handle_list(client_id, request)

    async def _handle_call_tool(
        self, client_id: str, request: CallToolRequest
    ) -> CallToolResult | Error:
        """Handle tools/call request from specific client."""
        if self.server_config.capabilities.tools is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support tools capability",
            )
        try:
            return await self.tools.handle_call(client_id, request)
        except KeyError:
            return Error(code=METHOD_NOT_FOUND, message=f"Unknown tool: {request.name}")

    # ================================
    # Prompts
    # ================================

    async def _handle_list_prompts(
        self, client_id: str, request: ListPromptsRequest
    ) -> ListPromptsResult | Error:
        """Handle prompts/list request from specific client."""
        if self.server_config.capabilities.prompts is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support prompts capability",
            )
        return await self.prompts.handle_list_prompts(client_id, request)

    async def _handle_get_prompt(
        self, client_id: str, request: GetPromptRequest
    ) -> GetPromptResult | Error:
        """Handle prompts/get request from specific client."""
        if self.server_config.capabilities.prompts is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support prompts capability",
            )
        try:
            return await self.prompts.handle_get_prompt(client_id, request)
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
        self, client_id: str, request: ListResourcesRequest
    ) -> ListResourcesResult | Error:
        """Handle resources/list request from specific client."""
        if self.server_config.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )

        return await self.resources.handle_list_resources(client_id, request)

    async def _handle_list_resource_templates(
        self, client_id: str, request: ListResourceTemplatesRequest
    ) -> ListResourceTemplatesResult | Error:
        """Handle resources/templates/list request from specific client."""
        if self.server_config.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        return await self.resources.handle_list_templates(client_id, request)

    async def _handle_read_resource(
        self, client_id: str, request: ReadResourceRequest
    ) -> ReadResourceResult | Error:
        """Handle resources/read request from specific client."""
        if self.server_config.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        try:
            return await self.resources.handle_read(client_id, request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Error reading resource",
            )

    async def _handle_subscribe(
        self, client_id: str, request: SubscribeRequest
    ) -> EmptyResult | Error:
        """Handle resources/subscribe request from specific client."""
        if not (
            self.server_config.capabilities.resources
            and self.server_config.capabilities.resources.subscribe
        ):
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resource subscription",
            )
        try:
            return await self.resources.handle_subscribe(client_id, request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))

    async def _handle_unsubscribe(
        self, client_id: str, request: UnsubscribeRequest
    ) -> EmptyResult | Error:
        """Handle resources/unsubscribe request from specific client."""
        if not (
            self.server_config.capabilities.resources
            and self.server_config.capabilities.resources.subscribe
        ):
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resource subscription",
            )
        try:
            return await self.resources.handle_unsubscribe(client_id, request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))

    # ================================
    # Completions
    # ================================

    async def _handle_complete(
        self, client_id: str, request: CompleteRequest
    ) -> CompleteResult | Error:
        """Handle completion/complete request from specific client."""
        if not self.server_config.capabilities.completions:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support completions capability",
            )
        try:
            return await self.completions.handle_complete(client_id, request)
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

    async def _handle_set_level(
        self, client_id: str, request: SetLevelRequest
    ) -> EmptyResult | Error:
        """Handle logging/setLevel request from specific client."""
        if not self.server_config.capabilities.logging:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support logging capability",
            )
        return await self.logging.handle_set_level(client_id, request)

    # ================================
    # Notifications
    # ================================

    async def _handle_cancelled(
        self, client_id: str, notification: CancelledNotification
    ) -> None:
        """Handle cancelled notification from specific client."""
        was_cancelled = await self._coordinator.cancel_request(
            client_id, notification.request_id
        )
        await self.callbacks.call_cancelled(client_id, notification)

    async def _handle_progress(
        self, client_id: str, notification: ProgressNotification
    ) -> None:
        """Handle progress notification from specific client.

        Progress notifications inform the server about the status of long-running
        operations. The server can use this information for logging, monitoring,
        or relaying progress to other interested parties.
        """
        await self.callbacks.call_progress(client_id, notification)

    async def _handle_roots_list_changed(
        self, client_id: str, notification: RootsListChangedNotification
    ) -> None:
        """Handle roots/list_changed notification from specific client."""
        pass

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

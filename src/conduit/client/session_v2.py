"""Client session implementation for MCP.

The ClientSession extends BaseSession with client-specific behavior:
- Initialization handshake with servers
- Server capability tracking and state management
- Request delegation to domain-specific managers
- Notification handling for server state changes

Key components:
- Managers: Handle domain logic (tools, resources, prompts, etc.)
- State tracking: Server capabilities, available resources/tools
- Callbacks: Notify application of server state changes
"""

import asyncio
from dataclasses import dataclass

from conduit.client.coordinator import ClientMessageCoordinator
from conduit.client.managers.callbacks import CallbackManager
from conduit.client.managers.elicitation import (
    ElicitationManager,
    ElicitationNotConfiguredError,
)
from conduit.client.managers.roots import RootsManager
from conduit.client.managers.sampling import SamplingManager, SamplingNotConfiguredError
from conduit.client.server_manager import ServerManager
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
from conduit.protocol.elicitation import ElicitRequest, ElicitResult
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
)
from conduit.protocol.logging import LoggingMessageNotification
from conduit.protocol.prompts import (
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
    Resource,
    ResourceListChangedNotification,
    ResourceTemplate,
    ResourceUpdatedNotification,
)
from conduit.protocol.roots import ListRootsRequest, ListRootsResult
from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult
from conduit.protocol.tools import (
    ListToolsRequest,
    ListToolsResult,
    ToolListChangedNotification,
)
from conduit.transport.client import ClientTransport


class InvalidProtocolVersionError(Exception):
    pass


@dataclass
class ClientConfig:
    client_info: Implementation
    capabilities: ClientCapabilities
    protocol_version: str = PROTOCOL_VERSION


class ClientSession:
    def __init__(self, transport: ClientTransport, config: ClientConfig):
        self.transport = transport
        self.client_config = config
        self._initialized = False

        self.server_manager = ServerManager()
        self.callbacks = CallbackManager()

        # Domain managers
        self.roots = RootsManager()
        self.sampling = SamplingManager()
        self.elicitation = ElicitationManager()

        self._coordinator = ClientMessageCoordinator(transport, self.server_manager)
        self._register_handlers()

    # ================================
    # Lifecycle
    # ================================

    async def start(self) -> None:
        """Begin accepting and processing server messages.

        Starts the background message loop that will handle incoming server
        messages and route them to the appropriate handlers.
        """
        await self._coordinator.start()

    async def stop(self) -> None:
        """Stop the session and clean up all state."""
        await self._coordinator.stop()
        self.server_manager.reset_server_state()

        self._initialized = False

    # ================================
    # Initialization
    # ================================

    async def initialize(self, timeout: float = 30.0) -> None:
        """Initialize your MCP session with the server.

        Performs the MCP handshake to establish a working connection. This starts
        the message loop and negotiates capabilities with the server. Call this
        once after creating your session—it's safe to call multiple times and
        will return the cached result on subsequent calls.

        Args:
            timeout: How long to wait for the server to respond (seconds).
                Defaults to 30 seconds.

        Returns:
            Server capabilities, version info, and optional setup instructions.

        Raises:
            TimeoutError: Server didn't respond within the timeout period.
            InvalidProtocolVersionError: Server uses an incompatible protocol version.
            ConnectionError: Network failure or server rejected the handshake.
        """
        if self._initialized:
            return

        await self.start()
        try:
            await asyncio.wait_for(self._do_initialize(), timeout)
        except asyncio.TimeoutError:
            await self.stop()
            raise TimeoutError(f"Initialization timed out after {timeout}s")
        except InvalidProtocolVersionError:
            await self.stop()
            raise
        except Exception as e:
            await self.stop()
            raise ConnectionError(f"Initialization failed: {e}") from e

    async def _do_initialize(self) -> None:
        """Execute the three-step MCP initialization handshake.

        1. Send InitializeRequest with client info and capabilities
        2. Validate the server's InitializeResult response
        3. Send InitializedNotification to complete the handshake

        Updates the server manager with the negotiated capabilities and info.

        Raises:
            RuntimeError: If the server returns an error or unexpected response type
                during initialization.
            InvalidProtocolVersionError: If the server uses an incompatible
                protocol version.
        """
        init_request = self._create_init_request()
        response = await self._coordinator.send_request(init_request)

        if isinstance(response, Error):
            raise RuntimeError(response.message)
        if not isinstance(response, InitializeResult):
            raise RuntimeError("Server returned unexpected response type")

        self._validate_protocol_version(response)

        await self._coordinator.send_notification(InitializedNotification())
        self.server_manager.initialize_server(
            capabilities=response.capabilities,
            info=response.server_info,
            protocol_version=self.client_config.protocol_version,  # must match client
            instructions=response.instructions,
        )
        self._initialized = True

    def _create_init_request(self) -> InitializeRequest:
        """Create an InitializeRequest with client info and capabilities.

        Returns:
            InitializeRequest with client info and capabilities.
        """
        return InitializeRequest(
            client_info=self.client_config.client_info,
            capabilities=self.client_config.capabilities,
            protocol_version=self.client_config.protocol_version,
        )

    def _validate_protocol_version(self, result: InitializeResult) -> None:
        """Ensure the server's protocol version matches the client's.

        Raises:
            InvalidProtocolVersionError: If the server uses an incompatible
                protocol version.
        """
        if result.protocol_version != self.client_config.protocol_version:
            raise InvalidProtocolVersionError(
                "Protocol version mismatch: client="
                f"{self.client_config.protocol_version}, "
                f"server={result.protocol_version}"
            )

    # ================================
    # Ping
    # ================================

    async def _handle_ping(self, request: PingRequest) -> EmptyResult:
        """Always returns an empty result.

        Server sends pings to check connection health.
        """
        return EmptyResult()

    # ================================
    # Roots
    # ================================

    async def _handle_list_roots(
        self, request: ListRootsRequest
    ) -> ListRootsResult | Error:
        """Handle server request for filesystem roots.

        Args:
            request: Parsed roots/list request from server.

        Returns:
            ListRootsResult: The available roots.
            Error: If the client doesn't support the roots capability.
        """
        if self.client_config.capabilities.roots is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support roots capability",
            )
        return await self.roots.handle_list_roots(request)

    # ================================
    # Sampling
    # ================================

    async def _handle_sampling(
        self, request: CreateMessageRequest
    ) -> CreateMessageResult | Error:
        """Handle server request for LLM sampling.

        Args:
            request: Parsed sampling/createMessage request from server.

        Returns:
            CreateMessageResult: The created message.
            Error: If the client doesn't support sampling, a handler is not configured,
                or the handler fails.
        """
        if not self.client_config.capabilities.sampling:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support sampling capability",
            )
        try:
            return await self.sampling.handle_create_message(request)
        except SamplingNotConfiguredError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Could not fulfill sampling request",
                data={"request": request},
            )

    # ================================
    # Elicitation
    # ================================

    async def _handle_elicitation(self, request: ElicitRequest) -> ElicitResult | Error:
        """Handle server request for elicitation.

        Args:
            request: Parsed elicitation/create request from server.

        Returns:
            ElicitResult: The elicitation result.
            Error: If the client doesn't support elicitation, a handler is not
                configured, or the handler fails.
        """
        if not self.client_config.capabilities.elicitation:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support elicitation capability",
            )
        try:
            return await self.elicitation.handle_elicitation(request)
        except ElicitationNotConfiguredError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Could not fulfill elicitation request",
                data={"request": request},
            )

    # ================================
    # Notifications
    # ================================

    async def _handle_cancelled(self, notification: CancelledNotification) -> None:
        """Cancels a request from the server and calls the registered callback."""
        was_cancelled = await self._coordinator.cancel_request_from_server(
            notification.request_id
        )
        await self.callbacks.call_cancelled(notification)

    async def _handle_progress(self, notification: ProgressNotification) -> None:
        """Calls the registered callback for progress updates."""
        await self.callbacks.call_progress(notification)

    async def _handle_prompts_list_changed(
        self, notification: PromptListChangedNotification
    ) -> None:
        """Fetches the updated prompts list and calls the registered callback.

        Note:
            Only calls the callback if the request succeeds with valid results.
            Failed requests and server errors are silently ignored to avoid
            disrupting the session.
        """
        try:
            list_prompts_result = await self.send_request(ListPromptsRequest())
            if isinstance(list_prompts_result, ListPromptsResult):
                self.server_manager.get_server_context().prompts = (
                    list_prompts_result.prompts
                )
                await self.callbacks.call_prompts_changed(list_prompts_result.prompts)
        except Exception:
            pass

    async def _handle_resources_list_changed(
        self, notification: ResourceListChangedNotification
    ) -> None:
        """Fetches the updated resources/templates and calls the registered callback.

        Note:
            Calls the callback when at least one request succeeds. Passes empty lists
            for failed requests. If both requests fail, the callback is not called.
        """
        resources: list[Resource] = []
        templates: list[ResourceTemplate] = []
        context = self.server_manager.get_server_context()

        try:
            list_resources_result = await self.send_request(ListResourcesRequest())
            if isinstance(list_resources_result, ListResourcesResult):
                context.resources = list_resources_result.resources
        except Exception:
            pass

        try:
            list_templates_result = await self.send_request(
                ListResourceTemplatesRequest()
            )
            if isinstance(list_templates_result, ListResourceTemplatesResult):
                context.resource_templates = list_templates_result.resource_templates
        except Exception:
            pass

        if resources or templates:
            await self.callbacks.call_resources_changed(resources, templates)

    async def _handle_resources_updated(
        self, notification: ResourceUpdatedNotification
    ) -> None:
        """Reads the updated resource content and calls the registered callback.

        Note:
            Only calls the callback if the resource read succeeds. Failed requests are
            silently ignored to avoid disrupting the session.
        """
        try:
            read_resource_result = await self.send_request(
                ReadResourceRequest(uri=notification.uri)
            )
            if isinstance(read_resource_result, ReadResourceResult):
                await self.callbacks.call_resource_updated(
                    notification.uri, read_resource_result
                )
        except Exception:
            pass

    async def _handle_tools_list_changed(
        self, notification: ToolListChangedNotification
    ) -> None:
        """Fetches the updated tools list and calls the registered callback.

        Note:
            Only calls the callback if the request succeeds with valid results.
            Failed requests and server errors are silently ignored to avoid
            disrupting the session.
        """
        try:
            list_tools_result = await self.send_request(ListToolsRequest())
            if isinstance(list_tools_result, ListToolsResult):
                self.server_manager.get_server_context().tools = list_tools_result.tools
                await self.callbacks.call_tools_changed(list_tools_result.tools)
        except Exception:
            pass

    async def _handle_logging_message(
        self, notification: LoggingMessageNotification
    ) -> None:
        """Calls the registered callback for logging messages."""
        await self.callbacks.call_logging_message(notification)

    # ================================
    # Send messages
    # ================================

    async def send_request(
        self, request: Request, timeout: float = 30.0
    ) -> Result | Error:
        """Sends a request to the server and waits for a response.

        Args:
            request: The request to send.
            timeout: Maximum time to wait for response in seconds (default 30s).

        Returns:
            Result | Error: The server's response or timeout error.

        Raises:
            ValueError: If attempting to send non-ping request to uninitialized server.
            ConnectionError: If the transport fails.
            TimeoutError: If server doesn't respond within timeout.
        """

        if (
            request.method not in ("ping", "initialize")
            and not self.server_manager.get_server_context().initialized
        ):
            raise ValueError(
                f"Cannot send {request.method} to uninitialized server. "
                "Only ping requests are allowed before initialization."
            )

        return await self._coordinator.send_request(request, timeout)

    async def send_notification(self, notification: Notification) -> None:
        """Sends a notification to the server.

        Args:
            notification: The notification to send.

        Raises:
            ConnectionError: If the transport fails.
        """
        await self._coordinator.send_notification(notification)

    # ================================
    # Register handlers
    # ================================

    def _register_handlers(self) -> None:
        """Registers all message handlers."""

        # Requests
        self._coordinator.register_request_handler("ping", self._handle_ping)
        self._coordinator.register_request_handler(
            "roots/list", self._handle_list_roots
        )
        self._coordinator.register_request_handler(
            "sampling/createMessage", self._handle_sampling
        )
        self._coordinator.register_request_handler(
            "elicitation/create", self._handle_elicitation
        )

        # Notifications
        self._coordinator.register_notification_handler(
            "notifications/cancelled", self._handle_cancelled
        )
        self._coordinator.register_notification_handler(
            "notifications/progress", self._handle_progress
        )
        self._coordinator.register_notification_handler(
            "notifications/prompts/list_changed", self._handle_prompts_list_changed
        )
        self._coordinator.register_notification_handler(
            "notifications/resources/list_changed", self._handle_resources_list_changed
        )

        self._coordinator.register_notification_handler(
            "notifications/resources/updated", self._handle_resources_updated
        )
        self._coordinator.register_notification_handler(
            "notifications/tools/list_changed", self._handle_tools_list_changed
        )
        self._coordinator.register_notification_handler(
            "notifications/message", self._handle_logging_message
        )

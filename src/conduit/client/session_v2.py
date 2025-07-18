"""Client session implementation for MCP.

Key components:
- Managers: Handle domain logic (elicitation, sampling, roots, etc.)
- State tracking: Server capabilities, available resources/tools
- Callbacks: Handle server state changes and notifications
"""

import asyncio
from dataclasses import dataclass
from typing import Any, cast

from conduit.client.callbacks import CallbackManager
from conduit.client.coordinator_v2 import MessageCoordinator
from conduit.client.protocol.elicitation import (
    ElicitationManager,
    ElicitationNotConfiguredError,
)
from conduit.client.protocol.roots_v2 import RootsManager
from conduit.client.protocol.sampling import SamplingManager, SamplingNotConfiguredError
from conduit.client.server_manager_v2 import ServerManager
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
from conduit.transport.client_v2 import ClientTransport


class InvalidProtocolVersionError(Exception):
    pass


class ServerInitializationError(Exception):
    """Raised when server initialization fails during the MCP handshake."""

    def __init__(self, server_id: str, message: str, error_code: int | None = None):
        self.server_id = server_id
        self.error_code = error_code
        super().__init__(f"Server '{server_id}' initialization failed: {message}")


@dataclass
class ClientConfig:
    client_info: Implementation
    capabilities: ClientCapabilities
    protocol_version: str = PROTOCOL_VERSION


class ClientSession:
    def __init__(self, transport: ClientTransport, config: ClientConfig):
        self.transport = transport
        self.client_config = config

        self.server_manager = ServerManager()
        self.callbacks = CallbackManager()

        # Domain managers
        self.roots = RootsManager()
        self.sampling = SamplingManager()
        self.elicitation = ElicitationManager()

        self._coordinator = MessageCoordinator(transport, self.server_manager)
        self._register_handlers()

    # ================================
    # Lifecycle
    # ================================

    async def _start(self) -> None:
        """Start accepting and processing server messages.

        Starts the background message loop that will handle incoming server
        messages and route them to the appropriate handlers.
        """
        await self._coordinator.start()

    async def _stop(self) -> None:
        """Stop accepting and processing server messages and clean up all state."""
        await self._coordinator.stop()

    async def _cleanup_server(self, server_id: str) -> None:
        """Cleans up all state for a specific server."""
        # Clean up domain managers
        self.roots.cleanup_server(server_id)
        # self.sampling.cleanup_server(server_id)
        # self.elicitation.cleanup_server(server_id)

        # Clean up server manager
        self.server_manager.cleanup_server(server_id)

        # Clean up transport
        await self.transport.disconnect_server(server_id)

    async def disconnect_server(self, server_id: str) -> None:
        """Disconnects from a server and cleans up all state."""
        await self._cleanup_server(server_id)

    async def disconnect_all_servers(self) -> None:
        """Disconnects from all servers and cleans up all state."""
        await self._stop()
        for server_id in self.server_manager.get_server_ids():
            await self._cleanup_server(server_id)

    # ================================
    # Initialization
    # ================================
    async def connect_server(
        self, server_id: str, connection_info: dict[str, Any], timeout: float = 30.0
    ) -> None:
        """Connect to a server and perform MCP initialization handshake.

        Args:
            server_id: Unique identifier for this server connection
            connection_info: Transport-specific connection details
            timeout: How long to wait for the server to respond (seconds).
                Defaults to 30 seconds.

        Raises:
            ValueError: If server_id is already initialized
            TimeoutError: Server didn't respond within the timeout period.
            InvalidProtocolVersionError: Server uses an incompatible protocol version.
            ConnectionError: Network failure or server rejected the handshake.
        """
        # Note: This check doesn't prevent concurrent initialization attempts
        # for the same server_id. Multiple calls will result in redundant work
        # but both will succeed and reach the same final state.
        if self.server_manager.is_protocol_initialized(server_id):
            return

        await self._start()

        try:
            # 1. Register server with transport
            await self.transport.add_server(server_id, connection_info)

            # 2. Register server with server manager
            self.server_manager.register_server(server_id)

            # 3. Do MCP initialization handshake
            await asyncio.wait_for(
                self._do_initialize_server(server_id, timeout), timeout
            )

        except asyncio.TimeoutError:
            await self._cleanup_server(server_id)
            raise TimeoutError(f"Connection to {server_id} timed out after {timeout}s")
        except InvalidProtocolVersionError:
            await self._cleanup_server(server_id)
            raise
        except Exception as e:
            await self._cleanup_server(server_id)
            raise ConnectionError(f"Connection to {server_id} failed: {e}") from e

    async def _do_initialize_server(
        self, server_id: str, timeout: float = 30.0
    ) -> None:
        """Executes the three-step MCP initialization handshake.

        1. Send InitializeRequest with client info and capabilities
        2. Validate the server's InitializeResult response
        3. Send InitializedNotification to complete the handshake

        Stores server capabilities and marks the server as initialized.

        Raises:
            ServerInitializationError: If the server returns an error during
                initialization.
            InvalidProtocolVersionError: If the server uses an incompatible
                protocol version.
        """
        init_request = self._create_init_request()
        response = await self.send_request(server_id, init_request, timeout)

        if isinstance(response, Error):
            raise ServerInitializationError(
                server_id,
                f"Server returned error: {response.message}",
                response.code,
            )
        response = cast(InitializeResult, response)

        self._validate_protocol_version(response)

        await self._coordinator.send_notification(server_id, InitializedNotification())
        self.server_manager.initialize_server(
            server_id=server_id,
            capabilities=response.capabilities,
            info=response.server_info,
            protocol_version=self.client_config.protocol_version,  # must match client
            instructions=response.instructions,
        )

    def _create_init_request(self) -> InitializeRequest:
        """Creates an InitializeRequest with client info and capabilities.

        Returns:
            InitializeRequest with client info and capabilities.
        """
        return InitializeRequest(
            client_info=self.client_config.client_info,
            capabilities=self.client_config.capabilities,
            protocol_version=self.client_config.protocol_version,
        )

    def _validate_protocol_version(self, result: InitializeResult) -> None:
        """Ensures the server's protocol version matches the client's.

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

    async def _handle_ping(self, server_id: str, request: PingRequest) -> EmptyResult:
        """Returns an empty result."""

        return EmptyResult()

    # ================================
    # Roots
    # ================================

    async def _handle_list_roots(
        self, server_id: str, request: ListRootsRequest
    ) -> ListRootsResult | Error:
        """Returns the roots available to the server.

        Returns:
            ListRootsResult: The available roots.
            Error: If roots are not supported.
        """
        if self.client_config.capabilities.roots is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support roots capability",
            )
        return await self.roots.handle_list_roots(server_id, request)

    # ================================
    # Sampling
    # ================================

    async def _handle_sampling(
        self, server_id: str, request: CreateMessageRequest
    ) -> CreateMessageResult | Error:
        """Creates a message using the configured sampling handler.

        Returns:
            CreateMessageResult: The created message.
            Error: If sampling is not supported, handler not configured,
                or handler fails.
        """
        if not self.client_config.capabilities.sampling:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support sampling capability",
            )
        try:
            return await self.sampling.handle_create_message(server_id, request)
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

    async def _handle_elicitation(
        self, server_id: str, request: ElicitRequest
    ) -> ElicitResult | Error:
        """Returns an elicitation result using the configured elicitation handler

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
            return await self.elicitation.handle_elicitation(server_id, request)
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

    async def _handle_cancelled(
        self, server_id: str, notification: CancelledNotification
    ) -> None:
        """Cancels a request from the server and calls the registered callback."""
        was_cancelled = await self._coordinator.cancel_request_from_server(
            server_id, notification.request_id
        )
        if was_cancelled:
            await self.callbacks.call_cancelled(server_id, notification)

    async def _handle_progress(
        self, server_id: str, notification: ProgressNotification
    ) -> None:
        """Calls the registered callback for progress updates."""
        await self.callbacks.call_progress(server_id, notification)

    async def _handle_prompts_list_changed(
        self, server_id: str, notification: PromptListChangedNotification
    ) -> None:
        """Fetches the updated prompts list and calls the registered callback.

        Note:
            Only calls the callback if the request succeeds with valid results.
            Failed requests and server errors are silently ignored to avoid
            disrupting the session.
        """
        try:
            list_prompts_result = await self.send_request(
                server_id, ListPromptsRequest()
            )
            if isinstance(list_prompts_result, ListPromptsResult):
                self.server_manager.get_server(
                    server_id
                ).prompts = list_prompts_result.prompts
                await self.callbacks.call_prompts_changed(
                    server_id, list_prompts_result.prompts
                )
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
                resources = list_resources_result.resources
                context.resources = resources
        except Exception:
            pass

        try:
            list_templates_result = await self.send_request(
                ListResourceTemplatesRequest()
            )
            if isinstance(list_templates_result, ListResourceTemplatesResult):
                templates = list_templates_result.resource_templates
                context.resource_templates = templates
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
        self, server_id: str, request: Request, timeout: float = 30.0
    ) -> Result | Error:
        """Send a request to a server and wait for a response.

        Args:
            server_id: The server to send the request to.
            request: The request to send.
            timeout: Maximum time to wait for response in seconds (default 30s).

        Returns:
            Result | Error: The server's response or timeout error.

        Raises:
            ValueError: If attempting to send non-ping/initialize request to
                uninitialized server.
            ConnectionError: If the transport fails.
            TimeoutError: If server doesn't respond within timeout.
        """
        await self._start()

        if request.method not in (
            "ping",
            "initialize",
        ) and not self.server_manager.is_protocol_initialized(server_id):
            raise ValueError(
                f"Cannot send {request.method} to uninitialized server. "
                "Only ping requests are allowed before initialization."
            )

        return await self._coordinator.send_request(server_id, request, timeout)

    async def send_notification(
        self, server_id: str, notification: Notification
    ) -> None:
        """Send a notification to a server.

        Args:
            server_id: The server to send the notification to.
            notification: The notification to send.

        Raises:
            ConnectionError: If the transport fails.
        """
        await self._start()

        await self._coordinator.send_notification(server_id, notification)

    # ================================
    # Register handlers
    # ================================

    def _register_handlers(self) -> None:
        """Registers all message handlers with the coordinator."""

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

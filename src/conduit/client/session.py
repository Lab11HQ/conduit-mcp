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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from conduit.client.managers.callbacks import CallbackManager
from conduit.client.managers.elicitation import (
    ElicitationManager,
    ElicitationNotConfiguredError,
)
from conduit.client.managers.roots import RootsManager
from conduit.client.managers.sampling import SamplingManager, SamplingNotConfiguredError
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
    ServerCapabilities,
)
from conduit.protocol.logging import LoggingMessageNotification
from conduit.protocol.prompts import (
    ListPromptsRequest,
    ListPromptsResult,
    Prompt,
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
    Tool,
    ToolListChangedNotification,
)
from conduit.protocol.unions import NOTIFICATION_REGISTRY
from conduit.shared.exceptions import UnknownNotificationError, UnknownRequestError
from conduit.shared.session import BaseSession
from conduit.transport.base import Transport

TRequest = TypeVar("TRequest", bound=Request)
TResult = TypeVar("TResult", bound=Result)
RequestHandler = Callable[[TRequest], Awaitable[TResult | Error]]
RequestRegistryEntry = tuple[type[TRequest], RequestHandler[TRequest, TResult]]
TNotification = TypeVar("TNotification", bound=Notification)
NotificationHandler = Callable[[TNotification], Awaitable[None]]


class InvalidProtocolVersionError(Exception):
    pass


@dataclass
class ClientConfig:
    client_info: Implementation
    capabilities: ClientCapabilities
    protocol_version: str = PROTOCOL_VERSION


@dataclass
class ServerState:
    capabilities: ServerCapabilities | None = None
    instructions: str | None = None
    info: Implementation | None = None

    tools: list[Tool] | None = None
    resources: list[Resource] | None = None
    resource_templates: list[ResourceTemplate] | None = None
    prompts: list[Prompt] | None = None


class ClientSession(BaseSession):
    def __init__(self, transport: Transport, config: ClientConfig):
        super().__init__(transport)
        self.client_config = config
        self._initialize_result: InitializeResult | None = None
        self.server_state = ServerState()
        self.callbacks = CallbackManager()

        # Domain managers
        self.roots = RootsManager()
        self.sampling = SamplingManager()
        self.elicitation = ElicitationManager()

    # ================================
    # Initialization
    # ================================

    @property
    def initialized(self) -> bool:
        return self._initialize_result is not None

    async def initialize(self, timeout: float = 30.0) -> InitializeResult:
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
        await self.start()

        if self._initialize_result:
            return self._initialize_result

        try:
            self._initialize_result = await asyncio.wait_for(
                self._do_initialize(), timeout
            )
            return self._initialize_result
        except asyncio.TimeoutError:
            await self.stop()
            raise TimeoutError(f"Initialization timed out after {timeout}s")
        except InvalidProtocolVersionError:
            await self.stop()
            raise
        except Exception as e:
            await self.stop()
            raise ConnectionError(f"Initialization failed: {e}") from e

    async def _do_initialize(self) -> InitializeResult:
        """Execute the three-step MCP initialization handshake.

        1. Send InitializeRequest with client info and capabilities
        2. Validate the server's InitializeResult response
        3. Send InitializedNotification to complete the handshake

        The server state is updated with the negotiated capabilities and info.

        Raises:
            RuntimeError: If the server returns an error or unexpected response type
                during initialization.
            InvalidProtocolVersionError: If the server uses an incompatible
                protocol version.
        """
        init_request = self._create_init_request()
        response = await self.send_request(init_request)

        if isinstance(response, Error):
            raise RuntimeError(response.message)
        if not isinstance(response, InitializeResult):
            raise RuntimeError("Server returned unexpected response type")

        self._validate_protocol_version(response)

        await self.send_notification(InitializedNotification())
        self._store_init_result(response)

        return response

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

    def _store_init_result(self, result: InitializeResult) -> None:
        """Store the server's capabilities, instructions, and info in the server state.

        Args:
            result: InitializeResult from server.
        """
        self.server_state.capabilities = result.capabilities
        self.server_state.instructions = result.instructions
        self.server_state.info = result.server_info

    # ================================
    # Request handlers
    # ================================

    async def _handle_session_request(self, payload: dict[str, Any]) -> Result | Error:
        """Handle client-specific requests by routing to appropriate handlers.

        Looks up the request method in the handler registry, parses the request
        payload into the appropriate protocol object, and delegates to the
        registered handler function.

        Args:
            payload: Raw JSON-RPC request payload.

        Returns:
            Result from the handler, or Error if handler returns one.

        Raises:
            UnknownRequestError: If the request method is not in the registry.

        Note:
            Handlers are responsible for capability checking and returning
            appropriate Error objects rather than raising exceptions.
        """
        method = payload["method"]

        registry = self._get_request_registry()
        if method not in registry:
            raise UnknownRequestError(method)

        request_class, handler = registry[method]
        request = request_class.from_protocol(payload)
        return await handler(request)

    def _get_request_registry(self) -> dict[str, RequestRegistryEntry]:
        """Get the request registry for the client session.

        The request registry is a dictionary that maps request methods to their
        corresponding request class and handler function.
        """
        return {
            "ping": (PingRequest, self._handle_ping),
            "roots/list": (ListRootsRequest, self._handle_list_roots),
            "sampling/createMessage": (CreateMessageRequest, self._handle_sampling),
            "elicitation/create": (ElicitRequest, self._handle_elicitation),
        }

    async def _handle_ping(self, request: PingRequest) -> EmptyResult | Error:
        """Handle server request for ping.

        Returns:
            PingResult with pong.
        """
        return EmptyResult()

    async def _handle_list_roots(
        self, request: ListRootsRequest
    ) -> ListRootsResult | Error:
        """Handle server request for filesystem roots.

        Only processes requests if the client advertised roots capability during
        initialization. Delegates actual roots logic to the RootsManager.

        Args:
            request: Parsed roots/list request from server.

        Returns:
            ListRootsResult from the roots manager, or Error if:
            - Client didn't advertise roots capability (METHOD_NOT_FOUND)
            - Handler raised unexpected exception (INTERNAL_ERROR)
        """
        if self.client_config.capabilities.roots is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support roots capability",
            )
        try:
            return await self.roots.handle_list_roots(request)
        except Exception:
            return Error(code=INTERNAL_ERROR, message="Error in roots handler")

    async def _handle_sampling(
        self, request: CreateMessageRequest
    ) -> CreateMessageResult | Error:
        """Handle server request for LLM sampling.

        Only processes requests if the client advertised sampling capability during
        initialization. Delegates actual sampling logic to the SamplingManager.

        Args:
            request: Parsed sampling/createMessage request from server.

        Returns:
            CreateMessageResult from the configured handler, or Error if:
            - Client didn't advertise sampling capability (METHOD_NOT_FOUND)
            - No sampling handler configured (METHOD_NOT_FOUND)
            - Handler raised unexpected exception (INTERNAL_ERROR)
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
            return Error(code=INTERNAL_ERROR, message="Error in sampling handler")

    async def _handle_elicitation(self, request: ElicitRequest) -> ElicitResult | Error:
        """Handle server request for elicitation.

        Only processes requests if the client advertised elicitation capability during
        initialization. Delegates actual elicitation logic to the ElicitationManager.

        Args:
            request: Parsed elicitation/create request from server.

        Returns:
            ElicitResult from the configured handler, or Error if:
            - Client didn't advertise elicitation capability (METHOD_NOT_FOUND)
            - No elicitation handler configured (METHOD_NOT_FOUND)
            - Handler raised unexpected exception (INTERNAL_ERROR)
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
            return Error(code=INTERNAL_ERROR, message="Error in elicitation handler")

    # ================================
    # Notification handlers
    # ================================

    async def _handle_session_notification(self, payload: dict[str, Any]) -> None:
        """Handle incoming notifications from the server.

        Parses the notification payload into the appropriate protocol object and
        routes it to the registered handler. Unlike requests, notifications are
        fire-and-forget - no response is sent back to the server.

        Notifications include server state changes (tools/resources/prompts changed),
        progress updates, cancellation notices, and logging messages.

        Args:
            payload: Raw JSON-RPC notification payload.

        Raises:
            UnknownNotificationError: If the notification type isn't recognized.

        Note:
            Only notifications with registered handlers are processed. Unknown
            notification types are rejected, but missing handlers are silently ignored.
        """
        method = payload["method"]
        notification_class = NOTIFICATION_REGISTRY.get(method)
        if notification_class is None:
            raise UnknownNotificationError(method)
        notification = notification_class.from_protocol(payload)

        registry = self._get_notification_registry()
        if method in registry:
            handler = registry[method]
            await handler(notification)

    def _get_notification_registry(self) -> dict[str, NotificationHandler]:
        return {
            "notifications/cancelled": self._handle_cancelled,
            "notifications/progress": self._handle_progress,
            "notifications/prompts/list_changed": self._handle_prompts_list_changed,
            "notifications/resources/list_changed": self._handle_resources_list_changed,
            "notifications/resources/updated": self._handle_resources_updated,
            "notifications/tools/list_changed": self._handle_tools_list_changed,
            "notifications/message": self._handle_logging_message,
        }

    async def _handle_cancelled(self, notification: CancelledNotification) -> None:
        """Handle server cancellation notifications for in-flight requests.

        Cancels the corresponding request task if it exists and notifies the
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
        """Handle server progress notifications.

        Delegates progress updates to the callback manager.

        Args:
            notification: Progress notification from server with progress token.
        """
        await self.callbacks.call_progress(notification)

    async def _handle_prompts_list_changed(
        self, notification: PromptListChangedNotification
    ) -> None:
        """Handle server notification that the prompts list has changed.

        Fetches the updated prompts list from the server, updates local server
        state, and calls the registered callback with the new prompts.

        Args:
            notification: Notification that prompts have changed (content ignored).

        Note:
            Only updates state and calls callback if the request succeeds with
            valid results. Failed requests and server errors are silently ignored
            to avoid disrupting the session.
        """
        try:
            result = await self.send_request(ListPromptsRequest())
            if isinstance(result, ListPromptsResult):
                self.server_state.prompts = result.prompts
                await self.callbacks.call_prompts_changed(result.prompts)
        except Exception:
            pass

    async def _handle_resources_list_changed(
        self, notification: ResourceListChangedNotification
    ) -> None:
        """Handle server notification that the resources list has changed.

        Fetches both the updated resources and resource templates from the server,
        updates local server state for successful requests, and calls the registered
        callback if at least one request succeeds.

        Args:
            notification: Notification that resources list has changed
                (content ignored).

        Note:
            Calls the callback when at least one request succeeds, passing empty
            lists for failed requests. If both requests fail, no callback is made.
        """
        resources: list[Resource] = []
        templates: list[ResourceTemplate] = []

        try:
            resources_result = await self.send_request(ListResourcesRequest())
            if isinstance(resources_result, ListResourcesResult):
                resources = resources_result.resources
                self.server_state.resources = resources
        except Exception:
            pass

        try:
            templates_result = await self.send_request(ListResourceTemplatesRequest())
            if isinstance(templates_result, ListResourceTemplatesResult):
                templates = templates_result.resource_templates
                self.server_state.resource_templates = templates
        except Exception:
            pass

        if resources or templates:
            await self.callbacks.call_resources_changed(resources, templates)

    async def _handle_resources_updated(
        self, notification: ResourceUpdatedNotification
    ) -> None:
        """Handle notification that a specific resource has been updated.

        Reads the updated resource content and calls the registered callback
        with the URI and fresh resource data.

        Args:
            notification: Notification with URI of the updated resource.

        Note:
            Only calls callback if the resource read succeeds. Failed requests
            are silently ignored to avoid disrupting the session.
        """
        try:
            result = await self.send_request(ReadResourceRequest(uri=notification.uri))
            if isinstance(result, ReadResourceResult):
                await self.callbacks.call_resource_updated(notification.uri, result)
        except Exception:
            pass

    async def _handle_tools_list_changed(
        self, notification: ToolListChangedNotification
    ) -> None:
        """Handle server notification that the tools list has changed.

        Fetches the updated tools list from the server, updates local server
        state, and calls the registered callback with the new tools.

        Args:
            notification: Notification that tools have changed (content ignored).

        Note:
            Only updates state and calls the callback if the request succeeds with
            valid results. Failed requests and server errors are silently ignored
            to avoid disrupting the session.
        """
        try:
            tools_result = await self.send_request(ListToolsRequest())
            if isinstance(tools_result, ListToolsResult):
                self.server_state.tools = tools_result.tools
                await self.callbacks.call_tools_changed(tools_result.tools)
        except Exception:
            pass

    async def _handle_logging_message(
        self, notification: LoggingMessageNotification
    ) -> None:
        """Handle server logging message notifications.

        Delegates logging messages to the callback manager.

        Args:
            notification: Logging message notification from server.
        """
        await self.callbacks.call_logging_message(notification)

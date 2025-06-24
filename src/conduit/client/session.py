"""Low-level MCP client session implementation.

This module contains the internal protocol engine that handles MCP communication.
Most users should use the higher-level MCPClient class instead—this is for when you
need direct control over the protocol lifecycle.

The ClientSession manages JSON-RPC message routing, maintains connection state,
and handles the MCP initialization handshake. It's designed to be wrapped by
more user-friendly interfaces.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import cast

from conduit.protocol.base import (
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
from conduit.protocol.jsonrpc import JSONRPCRequest
from conduit.protocol.logging import LoggingMessageNotification
from conduit.protocol.prompts import PromptListChangedNotification
from conduit.protocol.resources import (
    ResourceListChangedNotification,
    ResourceUpdatedNotification,
)
from conduit.protocol.roots import ListRootsRequest, ListRootsResult, Root
from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult
from conduit.protocol.tools import ToolListChangedNotification
from conduit.shared.session import BaseSession
from conduit.transport.base import Transport

CLIENT_NOTIFICATION_CLASSES: dict[str, type[Notification]] = {
    "notifications/cancelled": CancelledNotification,
    "notifications/message": LoggingMessageNotification,
    "notifications/progress": ProgressNotification,
    "notifications/resources/updated": ResourceUpdatedNotification,
    "notifications/resources/list_changed": ResourceListChangedNotification,
    "notifications/tools/list_changed": ToolListChangedNotification,
    "notifications/prompts/list_changed": PromptListChangedNotification,
}

CLIENT_REQUEST_CLASSES: dict[str, type[Request]] = {
    "ping": PingRequest,
    "roots/list": ListRootsRequest,
    "sampling/createMessage": CreateMessageRequest,
    "elicitation/create": ElicitRequest,
}


class ClientSession(BaseSession):
    """Manages the low-level MCP client protocol and connection lifecycle.

    Handles JSON-RPC message routing, request/response correlation, and
    server communication over a transport. This is the internal engine—
    most users should use the higher-level MCPClient class instead.

    Key responsibilities:
    - MCP initialization handshake
    - Bidirectional message processing (requests, responses, notifications)
    - Request timeout and cancellation handling
    - Type-safe protocol parsing and routing

    Args:
        transport: Communication channel to the MCP server.
        client_info: Client identification and version info.
        capabilities: What MCP features this client supports.
        create_message_handler: LLM sampling handler (required if sampling enabled).
        roots: Filesystem roots to expose (if roots capability enabled).

    Raises:
        ValueError: Sampling capability enabled without handler.
    """

    def __init__(
        self,
        transport: Transport,
        client_info: Implementation,
        capabilities: ClientCapabilities,
        create_message_handler: Callable[
            [CreateMessageRequest], Awaitable[CreateMessageResult]
        ]
        | None = None,
        roots: list[Root] | None = None,
        elicitation_handler: Callable[[ElicitRequest], Awaitable[ElicitResult]]
        | None = None,
    ):
        super().__init__(transport)
        self.client_info = client_info
        self.capabilities = capabilities

        if capabilities.sampling and create_message_handler is None:
            raise ValueError(
                "create_message_handler required when sampling capability is enabled."
                " Either provide a handler or disable sampling in ClientCapabilities."
            )
        if capabilities.elicitation and elicitation_handler is None:
            raise ValueError(
                "elicitation_handler required when elicitation capability is enabled."
                " Either provide a handler or disable elicitation in "
                "ClientCapabilities."
            )
        self._create_message_handler = create_message_handler
        self._elicitation_handler = elicitation_handler
        self.roots = roots or []  # TODO: Hook this up to notifcations.
        self._initializing: asyncio.Future[InitializeResult] | None = None
        self._initialize_result: InitializeResult | None = None

    @property
    def initialized(self) -> bool:
        return self._initialize_result is not None

    async def initialize(self, timeout: float = 30.0) -> InitializeResult:
        """Initialize your MCP session with the server.

        Call this once after creating your session—it handles the handshake and
        starts the message loop. Safe to call multiple times.

        Args:
            timeout: How long to wait for the server (seconds).

        Returns:
            Server capabilities and connection details.

        Raises:
            TimeoutError: Server didn't respond in time.
            ValueError: Server uses incompatible protocol version.
            ConnectionError: Connection failed during handshake.
        """
        await self.start_message_loop()

        if self._initialize_result is not None:
            return self._initialize_result

        if self._initializing:
            return await self._initializing

        self._initializing = asyncio.create_task(self._do_initialize(timeout))
        try:
            result = await self._initializing
            return result
        finally:
            self._initializing = None

    async def send_request(
        self,
        request: Request,
        timeout: float = 30.0,
    ) -> Result | Error | None:
        """Send a request to the server and wait for its response.

        Handles the complete request lifecycle for you—generates IDs, manages
        timeouts, and cleans up automatically. Returns None for fire-and-forget
        requests like logging changes.

        Most requests require an initialized session. PingRequests work anytime
        since they test basic connectivity.

        Args:
            request: The MCP request to send
            timeout: How long to wait for a response (seconds)

        Returns:
            Server's response, or None for requests that don't expect replies.

        Raises:
            RuntimeError: Session not initialized (call initialize() first)
            TimeoutError: Server didn't respond in time
        """
        await self.start_message_loop()

        if not self.initialized and not isinstance(request, PingRequest):
            raise RuntimeError(
                "Session must be initialized before sending non-ping requests. "
                "Call initialize() first."
            )

        # Generate request ID and create JSON-RPC wrapper
        request_id = str(uuid.uuid4())
        jsonrpc_request = JSONRPCRequest.from_request(request, request_id)

        # If the request doesn't have a result type, we don't need to wait for a
        # response.
        if request.expected_result_type() is None:
            await self.transport.send(jsonrpc_request.to_wire())
            return

        future: asyncio.Future[Result | Error] = asyncio.Future()
        self._pending_requests[request_id] = (request, future)

        try:
            await self.transport.send(jsonrpc_request.to_wire())
            result = await asyncio.wait_for(future, timeout)
            return result
        except asyncio.TimeoutError:
            try:
                cancelled_notification = CancelledNotification(
                    request_id=request_id,
                    reason="Request timed out",
                )
                await self.send_notification(cancelled_notification)
            except Exception as e:
                print(f"Error sending cancellation notification: {e}")
            raise TimeoutError(f"Request {request_id} timed out after {timeout}s")
        finally:
            self._pending_requests.pop(request_id, None)

    async def _do_initialize(self, timeout: float = 30.0) -> InitializeResult:
        """Execute the MCP initialization handshake.

        Performs the three-step protocol: send request, validate response,
        send completion notification. Stops the session on any failure to
        prevent partial initialization.

        Args:
            timeout: Maximum seconds to wait for server response.

        Returns:
            Validated server initialization result.

        Raises:
            TimeoutError: Server didn't respond in time.
            ValueError: Protocol version mismatch or server error.
            ConnectionError: Transport failure.
        """
        await self.start_message_loop()
        init_request = InitializeRequest(
            client_info=self.client_info,
            capabilities=self.capabilities,
        )
        request_id = str(uuid.uuid4())
        jsonrpc_request = JSONRPCRequest.from_request(init_request, request_id)

        # Set up response waiting.
        future: asyncio.Future[Result | Error] = asyncio.Future()
        self._pending_requests[request_id] = (init_request, future)

        try:
            await self.transport.send(jsonrpc_request.to_wire())
            response = await asyncio.wait_for(future, timeout)
            if isinstance(response, Error):
                await self.close()
                raise ValueError(f"Initialization failed: {response}")

            init_result = cast(InitializeResult, response)
            if (
                init_result.protocol_version != PROTOCOL_VERSION
            ):  # TODO: Handle this better. SEND A INVALID_PARAMS ERROR.
                await self.close()
                raise ValueError(
                    f"Protocol version mismatch: client version {PROTOCOL_VERSION} !="
                    f" server version {init_result.protocol_version}"
                )

            initialized_notification = InitializedNotification()
            await self.send_notification(initialized_notification)

            self._initialize_result = init_result
            return init_result
        except asyncio.TimeoutError:
            await self.close()
            raise TimeoutError(f"Initialization timed out after {timeout}s")
        except Exception:
            await self.close()
            raise
        finally:
            self._pending_requests.pop(request_id, None)

    def _get_supported_notifications(self) -> dict[str, type[Notification]]:
        return CLIENT_NOTIFICATION_CLASSES

    def _get_supported_requests(self) -> dict[str, type[Request]]:
        return CLIENT_REQUEST_CLASSES

    async def _handle_session_request(self, request: Request) -> Result | Error:
        """Handle client-specific requests."""
        handler_method = {
            "ping": self._handle_ping,
            "roots/list": self._handle_list_roots,
            "sampling/createMessage": self._handle_create_message,
            "elicitation/create": self._handle_elicitation,
        }.get(request.method)
        if not handler_method:
            return Error(
                code=METHOD_NOT_FOUND,
                message=f"Unknown request method: {request.method}",
            )
        return await handler_method(request)

    async def _handle_ping(self, request: PingRequest) -> Result | Error:
        """Handle server request for ping.

        Returns:
            PingResult with pong.
        """
        return EmptyResult()

    async def _handle_list_roots(self, request: ListRootsRequest) -> Result | Error:
        """Handle server request for filesystem roots.

        Returns available roots if client advertised roots capability,
        otherwise METHOD_NOT_FOUND error.

        Args:
            request: Parsed roots/list request.

        Returns:
            ListRootsResult with roots, or Error if capability missing.
        """
        if self.capabilities.roots is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support roots capability",
            )
        return ListRootsResult(roots=self.roots)

    async def _handle_create_message(
        self, request: CreateMessageRequest
    ) -> Result | Error:
        """Handle server request for LLM message generation.

        Delegates to user-provided handler if sampling capability and handler
        are both configured, otherwise returns METHOD_NOT_FOUND.

        Args:
            request: Parsed sampling/createMessage request.

        Returns:
            CreateMessageResult from user handler, or Error if not configured.
        """
        if not self.capabilities.sampling:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support sampling capability",
            )

        if self._create_message_handler is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client not configured with a create message handler",
            )

        return await self._create_message_handler(request)

    async def _handle_elicitation(self, request: ElicitRequest) -> Result | Error:
        """Handle server request for elicitation.

        Args:
            request: Parsed elicitation/create request.

        Returns:
            ElicitResult from user handler, or Error if not configured.
        """
        # check if the client supports elicitation
        if not self.capabilities.elicitation:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support elicitation capability",
            )
        # check if the client has a elicitation handler
        if self._elicitation_handler is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client not configured with a elicitation handler",
            )
        return await self._elicitation_handler(request)

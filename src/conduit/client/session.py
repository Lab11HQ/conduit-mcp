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
from typing import Any, cast

from conduit.protocol import JSONRPCRequest, Request
from conduit.protocol.base import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    Error,
    Notification,
    Result,
)
from conduit.protocol.common import (
    CancelledNotification,
    EmptyResult,
    PingRequest,
    ProgressNotification,
)
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
)
from conduit.protocol.jsonrpc import JSONRPCError, JSONRPCNotification, JSONRPCResponse
from conduit.protocol.logging import LoggingMessageNotification
from conduit.protocol.prompts import PromptListChangedNotification
from conduit.protocol.resources import (
    ResourceListChangedNotification,
    ResourceUpdatedNotification,
)
from conduit.protocol.roots import ListRootsRequest, ListRootsResult, Root
from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult
from conduit.protocol.tools import ToolListChangedNotification
from conduit.shared.exceptions import UnknownNotificationError, UnknownRequestError
from conduit.transport.base import Transport

NOTIFICATION_CLASSES = {
    "notifications/cancelled": CancelledNotification,
    "notifications/message": LoggingMessageNotification,
    "notifications/progress": ProgressNotification,
    "notifications/resources/updated": ResourceUpdatedNotification,
    "notifications/resources/list_changed": ResourceListChangedNotification,
    "notifications/tools/list_changed": ToolListChangedNotification,
    "notifications/prompts/list_changed": PromptListChangedNotification,
}

REQUEST_CLASSES = {
    "ping": PingRequest,
    "roots/list": ListRootsRequest,
    "sampling/createMessage": CreateMessageRequest,
}


class ClientSession:
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
    ):
        self.transport = transport
        self.client_info = client_info
        self.capabilities = capabilities

        if capabilities.sampling and create_message_handler is None:
            raise ValueError(
                "create_message_handler required when sampling capability is enabled."
                " Either provide a handler or disable sampling in ClientCapabilities."
            )
        self._create_message_handler = create_message_handler

        self.roots = roots or []  # TODO: Hook this up to notifcations.
        self._pending_requests: dict[
            str, tuple[Request, asyncio.Future[Result | Error]]
        ] = {}
        self._message_loop_task: asyncio.Task[None] | None = None
        self._running = False
        self._initializing: asyncio.Future[InitializeResult] | None = None
        self._initialize_result: InitializeResult | None = None
        self.notifications: asyncio.Queue[Notification] = asyncio.Queue()

    async def _start(self) -> None:
        """Start the background message loop if not already running.

        Enables real-time handling of server requests, responses, and notifications.
        Safe to call multiple times.
        """
        if self._running:
            return
        self._running = True
        self._message_loop_task = asyncio.create_task(self._message_loop())

    async def stop(self) -> None:
        """Stop the session and clean up all resources.

        Cancels pending requests, closes the transport, and shuts down the message
        loop. Once stopped, you'll need to create a new session to reconnect.

        Safe to call multiple times.
        """
        if not self._running and self._message_loop_task is None:
            return

        self._running = False
        if self._message_loop_task:
            self._message_loop_task.cancel()
            try:
                await self._message_loop_task
            except asyncio.CancelledError:
                pass
            self._message_loop_task = None

        # Reset session state
        self._initialize_result = None
        self._initializing = None

        await self.transport.close()

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
        await self._start()

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
        await self._start()

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

    async def send_notification(
        self,
        notification: Notification,
    ) -> None:
        """Send a notification to the server.

        Fire-and-forget messaging—no initialization required, no response expected.

        Args:
            notification: The MCP notification to send

        Raises:
            Transport errors if sending fails.
        """
        await self._start()
        jsonrpc_notification = JSONRPCNotification.from_notification(notification)
        await self.transport.send(jsonrpc_notification.to_wire())

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
        await self._start()
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
                await self.stop()
                raise ValueError(f"Initialization failed: {response}")

            init_result = cast(InitializeResult, response)
            if (
                init_result.protocol_version != PROTOCOL_VERSION
            ):  # TODO: Handle this better. SEND A INVALID_PARAMS ERROR.
                await self.stop()
                raise ValueError(
                    f"Protocol version mismatch: client version {PROTOCOL_VERSION} !="
                    f" server version {init_result.protocol_version}"
                )

            initialized_notification = InitializedNotification()
            await self.send_notification(initialized_notification)

            self._initialize_result = init_result
            return init_result
        except asyncio.TimeoutError:
            await self.stop()
            raise TimeoutError(f"Initialization timed out after {timeout}s")
        except Exception:
            await self.stop()
            raise
        finally:
            self._pending_requests.pop(request_id, None)

    async def _message_loop(self) -> None:
        """Process incoming messages until the session stops.

        Runs continuously in the background, handling server requests, responses,
        and notifications. Recovers from message handling errors but stops on
        transport failures.
        """
        try:
            async for transport_message in self.transport.messages():
                if not self._running:
                    break
                try:
                    await self._handle_message(transport_message.payload)
                except Exception as e:
                    print(f"Error handling message: {e}")
                    continue

        except ConnectionError:
            print("Transport connection lost")
        except Exception as e:
            print("Transport error while receiving message:", e)
        finally:
            self._running = False
            self._cancel_pending_requests("Message loop terminated")

    def _cancel_pending_requests(self, reason: str) -> None:
        """Cancel all pending requests with a CancelledError.

        Called during shutdown to prevent requests from hanging forever.

        Args:
            reason: Human-readable explanation for the cancellation.
        """
        for request_id, (request, future) in self._pending_requests.items():
            if not future.done():
                error = Error(
                    code=INTERNAL_ERROR,
                    message=f"Cancelled because: {reason}",
                )
                future.set_result(error)
        self._pending_requests.clear()

    async def _handle_message(
        self, payload: dict[str, Any] | list[dict[str, Any]]
    ) -> None:
        """Route incoming messages to the appropriate handler.

        Central dispatch point that identifies JSON-RPC message types and
        routes to response, request, or notification handlers. Handles
        batched messages recursively.

        Args:
            payload: JSON-RPC message or batch of messages.

        Raises:
            ValueError: Unknown message type.
        """
        # TODO: Add a recursion limit
        if isinstance(payload, list):
            for item in payload:
                await self._handle_message(item)
            return

        try:
            if self._is_valid_response(payload):
                await self._handle_response(payload)
            elif self._is_valid_request(payload):
                asyncio.create_task(
                    self._handle_request(payload),
                    name=f"handle_request_{payload.get('id', 'unknown')}",
                )
            elif self._is_valid_notification(payload):
                await self._handle_notification(payload)
            else:
                raise ValueError(f"Unknown message type: {payload}")
        except Exception as e:
            print("Error handling message", e)
            raise

    def _is_valid_response(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC response.

        Validates ID field and ensures exactly one of 'result' or 'error'
        is present for safe routing to pending requests.

        Args:
            payload: JSON-RPC message payload.

        Returns:
            True if valid response structure.
        """
        has_valid_id = payload.get("id") is not None and isinstance(
            payload.get("id"), int | str
        )
        has_result = "result" in payload
        has_error = "error" in payload
        has_exactly_one_response_field = has_result ^ has_error

        return has_valid_id and has_exactly_one_response_field

    def _is_valid_request(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC request.

        Validates required 'method' and 'id' fields for safe routing.

        Args:
            payload: JSON-RPC message payload.

        Returns:
            True if valid request structure.
        """
        has_valid_id = payload.get("id") is not None and isinstance(
            payload.get("id"), int | str
        )
        return "method" in payload and has_valid_id

    def _is_valid_notification(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC notification.

        Validates 'method' field is present and 'id' field is absent
        (notifications don't expect responses).

        Args:
            payload: JSON-RPC message payload.

        Returns:
            True if valid notification structure.
        """
        return "method" in payload and "id" not in payload

    async def _handle_response(self, payload: dict[str, Any]) -> None:
        """Resolve a pending request with the server's response.

        Matches response to original request by ID, parses into Result or Error,
        and resolves the waiting future. Logs unmatched responses.

        Args:
            payload: Validated JSON-RPC response.
        """
        message_id = payload["id"]

        if message_id in self._pending_requests:
            original_request, future = self._pending_requests[message_id]
            result_or_error = self._parse_response(payload, original_request)
            future.set_result(result_or_error)
        else:
            print(f"Unmatched response for request ID {message_id}")

    def _parse_response(
        self, payload: dict[str, Any], original_request: Request
    ) -> Result | Error:
        """Parse JSON-RPC response into typed Result or Error objects.

        Uses the original request's type information to return the specific
        Result subclass (e.g., ListToolsResult) rather than generic dictionaries.

        Args:
            payload: Raw JSON-RPC response from server.
            original_request: Request that triggered this response.

        Returns:
            Typed Result object for success, or Error object for failures.

        Raises:
            ValueError: Request does not expect a result.
        """
        if "result" in payload:
            result_type = original_request.expected_result_type()
            if result_type is None:
                raise ValueError(
                    f"Request type {type(original_request).__name__} "
                    f"(method: {original_request.method}) is missing "
                    "expected_result_type() implementation"
                )
            return result_type.from_protocol(payload)
        return Error.from_protocol(payload)

    async def _handle_notification(self, payload: dict[str, Any]) -> None:
        """Parse notification and queue it for client consumption.

        Args:
            payload: Validated JSON-RPC notification.

        Raises:
            UnknownNotificationError: Unrecognized notification method.
        """
        notification = self._parse_notification(payload)
        await self.notifications.put(notification)

    def _parse_notification(self, payload: dict[str, Any]) -> Notification:
        """Parse JSON-RPC notification into typed notification object.

        Looks up the method in the notification registry and returns the
        appropriate typed object instead of raw dictionaries.

        Args:
            payload: JSON-RPC notification with 'method' field.

        Returns:
            Typed notification object for the method.

        Raises:
            UnknownNotificationError: Unrecognized notification method.
        """
        method = payload["method"]
        notification_class = NOTIFICATION_CLASSES.get(method)
        if notification_class is None:
            raise UnknownNotificationError(method)
        return notification_class.from_protocol(payload)

    async def _handle_request(self, payload: dict[str, Any]) -> None:
        """Handle server request and send back a response.

        Parses the request, routes to appropriate handler, and always sends
        a response—either the handler result or an error for unknown methods
        and exceptions.

        Args:
            payload: Validated JSON-RPC request.
        """
        message_id = payload["id"]

        try:
            request = self._parse_request(payload)
            result_or_error = await self._route_request(request)

            if isinstance(result_or_error, Result):
                response = JSONRPCResponse.from_result(result_or_error, message_id)
            else:  # Error
                response = JSONRPCError.from_error(result_or_error, message_id)

            await self.transport.send(response.to_wire())

        except UnknownRequestError as e:
            error = Error(
                code=METHOD_NOT_FOUND,
                message=f"Unknown request method: {e.method}",
            )
            error_response = JSONRPCError.from_error(error, message_id)
            await self.transport.send(error_response.to_wire())

        except Exception:
            # Unexpected error during request handling
            error = Error(
                code=INTERNAL_ERROR, message="Internal error processing request"
            )
            error_response = JSONRPCError.from_error(error, message_id)
            await self.transport.send(error_response.to_wire())

    def _parse_request(self, payload: dict[str, Any]) -> Request:
        """Parse JSON-RPC request into typed request object.

        Looks up the method in the request registry and returns the
        appropriate typed object instead of raw dictionaries.

        Args:
            payload: JSON-RPC request with 'method' field.

        Returns:
            Typed request object for the method.

        Raises:
            UnknownRequestError: Unrecognized request method.
        """
        method = payload["method"]
        request_class = REQUEST_CLASSES.get(method)
        if request_class is None:
            raise UnknownRequestError(method)
        return request_class.from_protocol(payload)

    async def _route_request(self, request: Request) -> Result | Error:
        """Route request to the appropriate handler method.

        Maps request methods to handler functions. Returns METHOD_NOT_FOUND
        error for unsupported methods instead of crashing.

        Args:
            request: Typed request object.

        Returns:
            Handler result or Error for unsupported methods.
        """
        handler_method = {
            "ping": self._handle_ping,
            "roots/list": self._handle_list_roots,
            "sampling/createMessage": self._handle_create_message,
        }.get(request.method)

        if not handler_method:
            return Error(
                code=METHOD_NOT_FOUND,
                message=f"Unknown request method: {request.method}",
            )

        return await handler_method(request)

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

    async def _handle_ping(self, request: PingRequest) -> Result:
        """Handle server ping request.

        Simple connectivity test—always returns success.

        Args:
            request: Parsed ping request.

        Returns:
            EmptyResult indicating successful response.
        """
        return EmptyResult()

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

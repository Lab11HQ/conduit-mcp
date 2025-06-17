import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from conduit.protocol import CallToolRequest, CallToolResult, JSONRPCRequest, Request
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
from conduit.transport.base import Transport, TransportMessage

from conduit.shared.exceptions import UnknownNotificationError, UnknownRequestError

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
    """
    MCP client session handling request/response over a transport.
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
        self._handle_create_message = create_message_handler

        self.roots = roots or []  # TODO: Hook this up to notifcations.

        self._request_id = 0
        self._pending_requests: dict[int, asyncio.Future[Any]] = {}
        self._message_loop_task: asyncio.Task[None] | None = None
        self._running = False
        self._initializing: asyncio.Future[InitializeResult] | None = None
        self._initialize_result: InitializeResult | None = None
        self._initialized = False
        self.notifications: asyncio.Queue[
            tuple[Notification, dict[str, Any] | None]
        ] = asyncio.Queue()

    async def _start(self) -> None:
        """
        Start the session's background message processing loop.

        Creates a task to continuously process incoming messages, enabling
        real-time handling of server requests and notifications.

        Called automatically by initialize(). Idempotent - safe to call multiple times.
        """
        if self._running:
            return
        self._running = True
        self._message_loop_task = asyncio.create_task(self._message_loop())

    async def stop(self) -> None:
        """
        Stop the session and clean up all resources.

        Terminates the background message loop, cancels any pending requests,
        and closes the transport connection. After calling this, the session
        cannot be restarted.

        Safe to call multiple times - subsequent calls do nothing.
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
        self._initialized = False
        self._initialize_result = None
        self._initializing = None

        await self.transport.close()

    async def initialize(
        self, transport_metadata: dict[str, Any] | None = None, timeout: float = 30.0
    ) -> InitializeResult:
        """
        Initialize the MCP session with the server.

        Performs the required MCP handshake: sends an InitializeRequest with this
        client's capabilities, waits for the server's InitializeResult, validates
        protocol compatibility, and sends the final InitializedNotification.

        This automatically starts the session's message loop if it isn't already
        running. After successful initialization, the session is ready for normal
        operation.

        Args:
            transport_metadata: Optional metadata to include with initialization
                messages. The meaning depends on your transport implementation.
            timeout: Maximum time in seconds to wait for server response.
                Defaults to 30 seconds.

        Returns:
            The server's initialization result, containing its capabilities, name,
            version, and protocol version.

        Raises:
            TimeoutError: If the server doesn't respond within the timeout period.
            ValueError: If the server uses an incompatible protocol version.
            ConnectionError: If the transport fails during initialization.

        Note:
            This method is idempotent. Multiple calls return the same result
            without re-initializing. If initialization is already in progress,
            this waits for it to complete.
        """
        if self._initialized and self._initialize_result is not None:
            return self._initialize_result

        if self._initializing:
            return await self._initializing

        self._initializing = asyncio.create_task(
            self._do_initialize(transport_metadata, timeout)
        )
        try:
            result = await self._initializing
            return result
        finally:
            self._initializing = None

    async def _ensure_initialized(self) -> None:
        """
        Ensure the session is initialized, triggering initialization if needed.

        This is a convenience method for internal operations that require an
        initialized session. If the session is already initialized, returns
        immediately. If initialization is in progress, waits for it to complete.
        Otherwise, starts initialization with default parameters.

        This method is used internally before operations like sending requests
        or accessing server capabilities, ensuring the session is ready without
        requiring callers to manage initialization state.

        Raises:
            ValueError: If initialization fails due to protocol incompatibility.
            ConnectionError: If transport operations fail during initialization.
            Any exception that initialize() might raise.

        Note:
            This is an internal helper. External code should call initialize()
            directly for explicit control over initialization parameters.
        """
        if self._initialized:
            return

        if self._initializing:
            await self._initializing
            return

        await self.initialize()

    async def _do_initialize(
        self, transport_metadata: dict[str, Any] | None = None, timeout: float = 30.0
    ) -> InitializeResult:
        """
        Execute the complete MCP initialization sequence with timeout handling.

        Implements the three-step MCP handshake protocol:
        1. Send InitializeRequest with client info and capabilities
        2. Receive and validate InitializeResult from server (with timeout)
        3. Send InitializedNotification to complete the handshake

        This method handles the low-level protocol details including request ID
        management, response correlation, and protocol version validation. If the
        server doesn't respond within the timeout, we stop the session. On any failure,
        we stop the session to prevent partial initialization states.

        Args:
            transport_metadata: Optional metadata passed to transport operations.
            timeout: Maximum time in seconds to wait for server response.

        Returns:
            The validated server initialization result.

        Raises:
            TimeoutError: If server doesn't respond within the timeout period.
            ValueError: If server protocol version is incompatible.
            ConnectionError: If transport operations fail.
            Any exception raised by the server or transport layer.

        Note:
            This is an internal implementation method. Use initialize() instead,
            which provides idempotency and concurrent call handling.
        """
        await self._start()
        init_request = InitializeRequest(
            client_info=self.client_info,
            capabilities=self.capabilities,
        )
        request_id = self._request_id
        self._request_id += 1
        jsonrpc_request = JSONRPCRequest.from_request(init_request, request_id)

        # Set up response waiting.
        future: asyncio.Future[Any] = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            await self.transport.send(jsonrpc_request.to_wire(), transport_metadata)
            result_data, _ = await asyncio.wait_for(future, timeout)
            init_result = InitializeResult.from_protocol(result_data)
            if (
                init_result.protocol_version != PROTOCOL_VERSION
            ):  # TODO: Handle this better. SEND A INVALID_PARAMS ERROR.
                await self.stop()
                raise ValueError(
                    f"Protocol version mismatch: client version {PROTOCOL_VERSION} !="
                    f" server version {init_result.protocol_version}"
                )

            initialized_notification = InitializedNotification()
            await self.send_notification(initialized_notification, transport_metadata)

            self._initialized = True
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

    async def send_request(
        self,
        request: Request,
        transport_metadata: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Send a request and wait for a response.

        Remove the request from the pending requests dictionary when the response is
        received.

        Args:
            request: The request to send
            transport_metadata: Transport specific metadata to send with the request
                (auth tokens, etc.)
            timeout: Timeout in seconds for the request.

        Returns:
            tuple[Any, dict[str, Any] | None]: The result and transport metadata.
                (result, transport_metadata).
        """
        await self._start()
        await self._ensure_initialized()

        # Generate request ID and create JSON-RPC wrapper
        request_id = self._request_id
        self._request_id += 1
        jsonrpc_request = JSONRPCRequest.from_request(request, request_id)

        future: asyncio.Future[Any] = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            await self.transport.send(jsonrpc_request.to_wire(), transport_metadata)
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            cancelled_notification = CancelledNotification(
                request_id=request_id,
                reason="Request timed out",
            )
            await self.send_notification(cancelled_notification, transport_metadata)
            raise TimeoutError(f"Request {request_id} timed out after {timeout}s")
        finally:
            self._pending_requests.pop(request_id, None)

    async def send_notification(
        self,
        notification: Notification,
        transport_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Send a notification to the server."""
        await self._start()
        jsonrpc_notification = JSONRPCNotification.from_notification(notification)
        await self.transport.send(jsonrpc_notification.to_wire(), transport_metadata)

    async def _message_loop(self) -> None:
        """Keeps the session alive by processing messages from the server.

        This runs continuously in the background, receiving messages from the transport
        and handing them to the message handler. Think of it as the session's main
        thread—it never stops listening until the connection dies or you shut it down.

        When a message arrives, the loop hands it off to `_handle_message()` and keeps
        going. If the message handler crashes on a given message, the loop logs the
        error and moves on to the next message. One bad message won't kill your session.

        But transport failures are different. If the connection breaks or the transport
        itself fails, the loop shuts down cleanly. It cancels any requests still waiting
        for responses so your code doesn't hang forever.

        The loop processes messages sequentially. The message handler decides how each
        message type should be processed (some may spawn concurrent tasks, others run
        inline).

        Stops when:
        - You call `stop()`
        - Connection breaks
        - Transport fails catastrophically
        """
        try:
            async for message in self.transport.messages():
                # Check if we should stop processing
                if not self._running:
                    break
                # NOTE: If we call stop() while this is running, shutdown will happen after
                # this message is processed. Shutdown not immediate.
                try:
                    await self._handle_message(message)
                except Exception as e:
                    print(f"Error handling message: {e}")
                    # Continue processing other messages
                    continue

        except ConnectionError:
            print("Transport connection lost")
        except Exception as e:
            print("Transport error while receiving message:", e)
        finally:
            self._running = False
            self._cancel_pending_requests("Message loop terminated")

    def _cancel_pending_requests(self, reason: str) -> None:
        for request_id, future in self._pending_requests.items():
            if not future.done():
                future.set_exception(
                    ConnectionError(f"Request {request_id} cancelled: {reason}")
                )
        self._pending_requests.clear()

    async def _handle_message(self, message: TransportMessage) -> None:
        """Route incoming transport message to appropriate handler based on JSON-RPC
        type.

        This is the central message dispatch point for the client session. It examines
        the message payload to determine the JSON-RPC message type and routes
        accordingly:

        - **Responses**: Resolves pending request futures with the complete response
        - **Requests**: Creates async task to handle server requests and send responses
        - **Notifications**: Parses and queues notifications for client consumption

        Request handling is done in background tasks to avoid blocking the message loop
        while fulfilling requests.

        Args:
            message: Transport message containing JSON-RPC payload and transport metadata

        Raises:
            ValueError: If message payload doesn't match any known JSON-RPC type
        """
        payload = message.payload

        try:
            if self._is_valid_response(payload):
                await self._handle_response(payload, message.metadata)
            elif self._is_request(payload):
                asyncio.create_task(
                    self._handle_request(payload, message.metadata),
                    name=f"handle_request_{payload.get('id', 'unknown')}",
                )
            elif self._is_notification(payload):
                await self._handle_notification(payload, message.metadata)
            else:
                raise ValueError(f"Unknown message type: {payload}")
        except Exception as e:
            print("Error handling message", e)
            raise

    def _is_valid_response(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a structurally valid JSON-RPC response.

        A valid response must have a non-null ID (to match against pending requests)
        and either a 'result' field for success or an 'error' field for failure.
        This validation ensures we can safely route the response to the right
        pending request.

        Args:
            payload: JSON-RPC message payload from transport

        Returns:
            True if payload can be processed as a response, False otherwise
        """
        return (
            "id" in payload
            and payload["id"] is not None
            and ("result" in payload or "error" in payload)
        )

    def _is_request(self, payload: dict[str, Any]) -> bool:
        return "method" in payload and "id" in payload and payload["id"] is not None

    def _is_notification(self, payload: dict[str, Any]) -> bool:
        return "method" in payload and "id" not in payload

    async def _handle_response(
        self, payload: dict[str, Any], transport_metadata: dict[str, Any] | None
    ) -> None:
        """Resolve a pending request with the server's response.

        When the server responds to one of our requests, this matches the response
        to the original request using the JSON-RPC ID and resolves the waiting
        future. This unblocks whatever code sent the request and lets it continue
        with the server's answer.

        Both successful responses (with 'result') and error responses (with 'error')
        resolve the future normally—the calling code decides how to interpret errors.

        Args:
            payload: Complete JSON-RPC response (validated by _is_valid_response)
            transport_metadata: Transport-specific metadata or None

        Note:
            If no pending request matches the response ID, this logs the unmatched
            response and continues. This can happen if requests timeout or in
            edge cases with transport behavior.
        """
        message_id = payload["id"]

        if message_id in self._pending_requests:
            future = self._pending_requests[message_id]
            future.set_result((payload, transport_metadata))
        else:
            print(f"Unmatched response for request ID {message_id}")

    async def _handle_notification(
        self, payload: dict[str, Any], transport_metadata: dict[str, Any] | None
    ) -> None:
        notification = self._parse_notification(payload)
        await self.notifications.put((notification, transport_metadata))

    def _parse_notification(self, payload: dict[str, Any]) -> Notification:
        method = payload["method"]
        notification_class = NOTIFICATION_CLASSES.get(method)
        if notification_class is None:
            raise UnknownNotificationError(method)
        return notification_class.from_protocol(payload)

    async def _handle_request(
        self, payload: dict[str, Any], transport_metadata: dict[str, Any] | None
    ) -> None:
        """Handle incoming request from server."""
        message_id = payload["id"]

        try:
            request = self._parse_request(payload)
            result_or_error = await self._route_request(request)

            if isinstance(result_or_error, Result):
                response = JSONRPCResponse.from_result(result_or_error, message_id)
            else:  # Error
                response = JSONRPCError.from_error(result_or_error, message_id)

            await self.transport.send(response.to_wire(), transport_metadata)

        except UnknownRequestError as e:
            error = Error(
                code=METHOD_NOT_FOUND,
                message=f"Unknown request method: {e.method}",
            )
            error_response = JSONRPCError.from_error(error, message_id)
            await self.transport.send(error_response.to_wire(), transport_metadata)

        except Exception:
            # Unexpected error during request handling
            error = Error(
                code=INTERNAL_ERROR, message="Internal error processing request"
            )
            error_response = JSONRPCError.from_error(error, message_id)
            await self.transport.send(error_response.to_wire(), transport_metadata)

    def _parse_request(self, payload: dict[str, Any]) -> Request:
        method = payload["method"]
        request_class = REQUEST_CLASSES.get(method)
        if request_class is None:
            raise UnknownRequestError(method)
        return request_class.from_protocol(payload)

    async def _route_request(self, request: Request) -> Result | Error:
        """Route request to appropriate handler."""
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

    async def _handle_list_roots(self) -> Result | Error:
        """Handle roots/list request."""
        if self.capabilities.roots is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support roots capability",
            )
        return ListRootsResult(roots=self.roots)

    async def _handle_ping(self) -> Result:
        """Handle ping request."""
        return EmptyResult()

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        transport_metadata: dict[str, Any] | None = None,
        return_transport_metadata: bool = False,
    ) -> CallToolResult | tuple[CallToolResult, dict[str, Any] | None]:
        """Call a tool and return the result.

        Args:
            name: Name of the tool to call
            arguments: Arguments to pass to the tool
            transport_metadata: Metadata to send with the request (auth tokens, etc.)
            return_transport_metadata: If True, return (result, transport_metadata)
                tuple.

        Returns:
            CallToolResult if return_metadata=False, otherwise tuple of
            (result, metadata)

        Raises:
            MCPError: If the tool call fails. Check .transport_metadata for HTTP
            status, etc.
        """
        request = CallToolRequest(name=name, arguments=arguments)
        raw_result, transport_meta = await self.send_request(
            request, transport_metadata
        )
        result = CallToolResult.from_protocol(raw_result)

        return (result, transport_meta) if return_transport_metadata else result

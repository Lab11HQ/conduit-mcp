"""Message processing mechanics for server sessions.

Handles the message loop, routing, and parsing while keeping
the session focused on protocol logic rather than message processing.
"""

import asyncio
import uuid
from typing import Any, Awaitable, Callable, TypeVar

from conduit.protocol.base import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    Error,
    Notification,
    Request,
    Result,
)
from conduit.protocol.common import CancelledNotification
from conduit.protocol.jsonrpc import (
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)
from conduit.protocol.unions import NOTIFICATION_CLASSES, REQUEST_CLASSES
from conduit.transport.server import ClientMessage, ServerTransport

# Type variables
TRequest = TypeVar("TRequest", bound=Request)
TResult = TypeVar("TResult", bound=Result)
TNotification = TypeVar("TNotification", bound=Notification)

# Handler signatures - separate for requests vs notifications
RequestHandler = Callable[[str, TRequest], Awaitable[TResult | Error]]
NotificationHandler = Callable[[str, TNotification], Awaitable[None]]


class MessageCoordinator:
    """Coordinates all message flow for server sessions.

    Handles bidirectional message coordination: routes inbound requests/notifications
    from clients, sends outbound requests to clients, and manages response tracking.
    Keeps the session focused on protocol logic.
    """

    def __init__(self, transport: ServerTransport):
        self.transport = transport
        self._request_handlers: dict[str, RequestHandler] = {}
        self._notification_handlers: dict[str, NotificationHandler] = {}
        self._message_loop_task: asyncio.Task[None] | None = None

        # Client-specific request tracking.
        # NOTE: May want to allow non string request ids in the future.
        self._in_flight_requests: dict[str, dict[str, asyncio.Task[None]]] = {}
        # Structure: {client_id: {request_id: task}}

        # NEW: Outbound request tracking (server → client)
        self._pending_requests: dict[
            str, dict[str, asyncio.Future[Result | Error]]
        ] = {}
        # Structure: {client_id: {request_id: future}}

    @property
    def running(self) -> bool:
        """True if the message loop is actively processing messages."""
        return (
            self._message_loop_task is not None and not self._message_loop_task.done()
        )

    def register_request_handler(self, method: str, handler: RequestHandler) -> None:
        """Register a handler for a specific method.

        Args:
            method: JSON-RPC method name (e.g., "tools/list")
            handler: Async function that takes (client_id, typed_request) and handles it
        """
        self._request_handlers[method] = handler

    def register_notification_handler(
        self, method: str, handler: NotificationHandler
    ) -> None:
        """Register a handler for a specific method.

        Args:
            method: JSON-RPC method name (e.g., "tools/list")
            handler: Async function that takes (client_id, typed_notification) and
                handles it
        """
        self._notification_handlers[method] = handler

    async def start(self) -> None:
        """Start the message processing loop.

        Creates a background task that continuously reads and handles incoming
        messages until stop() is called.

        Safe to call multiple times - subsequent calls are ignored if already running.

        Raises:
            ConnectionError: If the transport is closed or unavailable.
        """
        if self.running:
            return
        if not self.transport.is_open:
            raise ConnectionError("Cannot start processor: transport is closed")

        self._message_loop_task = asyncio.create_task(self._message_loop())
        self._message_loop_task.add_done_callback(self._on_message_loop_done)

    async def stop(self) -> None:
        """Stop message processing and cancel in-flight requests.

        Cancels the background message processing task and any in-flight
        request handlers.

        Safe to call multiple times.
        """
        if not self.running:
            return

        if self._message_loop_task is not None:
            self._message_loop_task.cancel()
            try:
                await self._message_loop_task
            except asyncio.CancelledError:
                pass
            self._message_loop_task = None

        # Cancel in-flight requests
        # TODO: Implement this
        self._in_flight_requests.clear()

    async def _message_loop(self) -> None:
        """Process incoming client messages until cancelled or transport fails.

        Runs continuously in the background and hands off messages to registered
        handlers. Individual message handling errors are logged and don't interrupt
        the loop, but transport failures will stop message processing entirely.
        """
        try:
            async for client_message in self.transport.client_messages():
                try:
                    await self._handle_client_message(client_message)
                except Exception as e:
                    print(
                        f"Error handling message from {client_message.client_id}: {e}"
                    )
                    continue
        except Exception as e:
            print(f"Transport error: {e}")

    async def _handle_client_message(self, client_message: ClientMessage) -> None:
        """Route client message to appropriate handler with client context.

        Args:
            client_message: Message from client with ID and payload
        """
        payload = client_message.payload
        client_id = client_message.client_id

        if self._is_valid_request(payload):
            await self._handle_request(client_id, payload)
        elif self._is_valid_notification(payload):
            await self._handle_notification(client_id, payload)
        elif self._is_valid_response(payload):
            await self._handle_response(client_id, payload)
        else:
            print(f"Unknown message type from {client_id}: {payload}")

    async def _handle_request(self, client_id: str, payload: dict[str, Any]) -> None:
        """Parse and route typed request to handler.

        Parses raw JSON-RPC payload into typed Request object and routes to
        the appropriate handler. Parsing errors are sent back to the client.

        Args:
            client_id: ID of the client that sent the request
            payload: Raw JSON-RPC request payload
        """
        method = payload["method"]
        request_id = payload["id"]

        try:
            # Parse raw payload into typed request
            request_or_error = self._parse_request(payload)

            if isinstance(request_or_error, Error):
                # Send parsing error back to client
                response = JSONRPCError.from_error(request_or_error, request_id)
                await self.transport.send_to_client(client_id, response.to_wire())
                return

            # Route to handler with typed request
            if handler := self._request_handlers.get(method):
                # Run as background task to avoid blocking message loop
                task = asyncio.create_task(
                    self._execute_request_handler(
                        handler, client_id, request_or_error, request_id
                    ),
                    name=f"handle_{method}_{client_id}_{request_id}",
                )
                # Ensure client dict exists
                if client_id not in self._in_flight_requests:
                    self._in_flight_requests[client_id] = {}
                # Store by client and request
                self._in_flight_requests[client_id][str(request_id)] = task
                task.add_done_callback(
                    lambda t: self._in_flight_requests[client_id].pop(
                        str(request_id), None
                    )
                )
            else:
                # Send METHOD_NOT_FOUND error
                error = Error(
                    code=METHOD_NOT_FOUND, message=f"Unknown method: {method}"
                )
                response = JSONRPCError.from_error(error, request_id)
                await self.transport.send_to_client(client_id, response.to_wire())

        except Exception as e:
            # Handle unexpected parsing errors
            error = Error(
                code=INTERNAL_ERROR, message=f"Error processing request: {str(e)}"
            )
            response = JSONRPCError.from_error(error, request_id)
            await self.transport.send_to_client(client_id, response.to_wire())

    async def _execute_request_handler(
        self,
        handler: RequestHandler,
        client_id: str,
        request: Request,
        request_id: str | int,
    ) -> None:
        """Execute a request handler and send the appropriate response.

        Args:
            handler: The request handler to execute
            client_id: ID of the client that sent the request
            request: The parsed request object
            request_id: ID of the request for response correlation
        """
        try:
            # Execute the handler
            result_or_error = await handler(client_id, request)

            # Format response based on handler result
            if isinstance(result_or_error, Error):
                response = JSONRPCError.from_error(result_or_error, request_id)
            else:
                response = JSONRPCResponse.from_result(result_or_error, request_id)

            # Send response back to client
            await self.transport.send_to_client(client_id, response.to_wire())

        except Exception as e:
            # Handle unexpected handler failures
            error = Error(code=INTERNAL_ERROR, message=f"Handler error: {str(e)}")
            response = JSONRPCError.from_error(error, request_id)
            await self.transport.send_to_client(client_id, response.to_wire())

    async def _handle_notification(
        self, client_id: str, payload: dict[str, Any]
    ) -> None:
        """Parse and route typed notification to handler.

        Args:
            client_id: ID of the client that sent the notification
            payload: Raw JSON-RPC notification payload
        """
        method = payload["method"]

        try:
            # Parse raw payload into typed notification
            notification = self._parse_notification(payload)

            if notification is None:
                # Parsing failed - already logged
                return

            # Route to handler with typed notification
            if handler := self._notification_handlers.get(method):
                # Run as background task (notifications don't need responses)
                asyncio.create_task(
                    handler(client_id, notification),
                    name=f"handle_{method}_{client_id}",
                )
            else:
                print(f"Unknown notification '{method}' from {client_id}")

        except Exception as e:
            print(f"Error processing notification '{method}' from {client_id}: {e}")

    async def _handle_response(self, client_id: str, payload: dict[str, Any]) -> None:
        """Handle response from client to our outbound request."""
        request_id = payload.get("id")
        if not request_id:
            print(f"Response from {client_id} missing request ID")
            return

        # Check if this is a response to our outbound request
        if (
            client_id in self._pending_requests
            and str(request_id) in self._pending_requests[client_id]
        ):
            future = self._pending_requests[client_id].pop(str(request_id))

            if "error" in payload:
                # Convert JSON-RPC error to Error object
                error_data = payload["error"]
                error = Error(
                    code=error_data.get("code", INTERNAL_ERROR),
                    message=error_data.get("message", "Unknown error"),
                )
                future.set_result(error)
            else:
                # Parse successful response
                try:
                    result = self._parse_response(payload)
                    future.set_result(result)
                except Exception as e:
                    # Parsing failed - return internal error
                    error = Error(
                        code=INTERNAL_ERROR, message=f"Failed to parse response: {e}"
                    )
                    future.set_result(error)

    def _parse_request(self, payload: dict[str, Any]) -> Request | Error:
        """Parse a JSON-RPC request payload into a typed Request object or Error.

        Returns an Error object for any parsing failures instead of raising exceptions.

        Args:
            payload: Raw JSON-RPC request payload

        Returns:
            Typed Request object on success, or Error for parsing failures
        """
        method = payload["method"]
        request_class = REQUEST_CLASSES.get(method)

        if request_class is None:
            return Error(code=METHOD_NOT_FOUND, message=f"Unknown method: {method}")

        try:
            return request_class.from_protocol(payload)
        except Exception as e:
            return Error(
                code=INVALID_PARAMS,
                message=f"Failed to deserialize {method} request: {str(e)}",
                data={
                    "id": payload.get("id", "unknown"),
                    "method": method,
                    "params": payload.get("params", {}),
                },
            )

    def _parse_notification(self, payload: dict[str, Any]) -> Notification | None:
        """Parse a JSON-RPC notification payload into a typed Notification object.

        Returns None for unknown notification types since notifications are
        fire-and-forget.

        Args:
            payload: Raw JSON-RPC notification payload

        Returns:
            Typed Notification object on success, None for unknown types or parse
            failures
        """
        method = payload["method"]
        notification_class = NOTIFICATION_CLASSES.get(method)

        if notification_class is None:
            print(f"Unknown notification method: {method}")
            return None

        try:
            return notification_class.from_protocol(payload)
        except Exception as e:
            print(f"Failed to deserialize {method} notification: {e}")
            return None

    def _is_valid_request(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC request."""
        has_valid_id = payload.get("id") is not None and isinstance(
            payload.get("id"), (int, str)
        )
        return "method" in payload and has_valid_id

    def _is_valid_notification(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC notification."""
        return "method" in payload and "id" not in payload

    def _is_valid_response(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC response."""
        has_valid_id = payload.get("id") is not None and isinstance(
            payload.get("id"), (int, str)
        )
        has_result = "result" in payload
        has_error = "error" in payload
        has_exactly_one_response_field = has_result ^ has_error

        return has_valid_id and has_exactly_one_response_field

    def _on_message_loop_done(self, task: asyncio.Task[None]) -> None:
        """Clean up when message loop exits."""
        # Cancel any remaining in-flight requests
        # TODO: Implement this
        pass

    async def cancel_request(self, client_id: str, request_id: str | int) -> bool:
        """Cancel a specific request for a specific client."""
        if client_id not in self._in_flight_requests:
            return False

        request_id_str = str(request_id)
        if request_id_str not in self._in_flight_requests[client_id]:
            return False

        task = self._in_flight_requests[client_id][request_id_str]
        task.cancel()
        return True

    async def cancel_client_requests(self, client_id: str) -> int:
        """Cancel all requests for a specific client. Returns count cancelled."""
        if client_id not in self._in_flight_requests:
            return 0

        count = 0
        for task in self._in_flight_requests[client_id].values():
            task.cancel()
            count += 1

        return count

    async def send_request_to_client(
        self, client_id: str, request: Request, timeout: float = 30.0
    ) -> Result | Error:
        """Send a request to a specific client and wait for response.

        Generates a unique request ID, sends the request, and waits for the
        client's response. Handles timeouts with automatic cancellation.

        Args:
            client_id: ID of the client to send the request to
            request: The request object to send
            timeout: Maximum time to wait for response in seconds

        Returns:
            Result | Error: The client's response or timeout error

        Raises:
            ConnectionError: If transport is closed
            TimeoutError: If client doesn't respond within timeout
        """
        if not self.transport.is_open:
            raise ConnectionError("Cannot send request: transport is closed")

        # Generate request ID and create JSON-RPC wrapper
        request_id = str(uuid.uuid4())
        jsonrpc_request = JSONRPCRequest.from_request(request, request_id)

        # Set up response tracking
        if client_id not in self._pending_requests:
            self._pending_requests[client_id] = {}

        future: asyncio.Future[Result | Error] = asyncio.Future()
        self._pending_requests[client_id][request_id] = future

        try:
            await self.transport.send_to_client(client_id, jsonrpc_request.to_wire())
            result = await asyncio.wait_for(future, timeout)
            return result
        except asyncio.TimeoutError:
            # Clean up pending request
            self._pending_requests[client_id].pop(request_id, None)

            # Send cancellation notification to client
            try:
                cancelled_notification = CancelledNotification(
                    request_id=request_id,
                    reason="Request timed out",
                )
                await self._send_cancellation_to_client(
                    client_id, cancelled_notification
                )
            except Exception as e:
                print(f"Error sending cancellation to {client_id}: {e}")

            raise TimeoutError(f"Request {request_id} timed out after {timeout}s")

    async def _send_cancellation_to_client(
        self, client_id: str, notification: CancelledNotification
    ) -> None:
        """Send cancellation notification to a specific client."""
        jsonrpc_notification = JSONRPCNotification.from_notification(notification)
        await self.transport.send_to_client(client_id, jsonrpc_notification.to_wire())

    def _parse_response(self, payload: dict[str, Any]) -> Result:
        """Parse JSON-RPC response payload into typed Result object."""
        # This would need to handle different response types
        # For now, return a generic result - we'll need to enhance this
        # based on the request type that was sent
        return Result()  # Placeholder - needs proper implementation

    def cleanup_client(self, client_id: str) -> None:
        """Clean up all state for a disconnected client."""
        # Cancel in-flight requests FROM this client
        if client_id in self._in_flight_requests:
            for task in self._in_flight_requests[client_id].values():
                task.cancel()
            del self._in_flight_requests[client_id]

        # Cancel pending requests TO this client
        if client_id in self._pending_requests:
            for future in self._pending_requests[client_id].values():
                if not future.done():
                    future.set_exception(
                        ConnectionError(f"Client {client_id} disconnected")
                    )
            del self._pending_requests[client_id]

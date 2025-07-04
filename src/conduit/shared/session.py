"""Base session implementation shared between client and server."""

import asyncio
import uuid
from abc import ABC, abstractmethod
from typing import Any

from conduit.protocol.base import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    Error,
    Notification,
    Request,
    Result,
)
from conduit.protocol.common import CancelledNotification, PingRequest
from conduit.protocol.initialization import InitializeRequest
from conduit.protocol.jsonrpc import (
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)
from conduit.protocol.unions import NOTIFICATION_CLASSES, REQUEST_CLASSES
from conduit.shared.exceptions import UnknownRequestError
from conduit.transport.base import Transport


class BaseSession(ABC):
    """Base class for MCP session implementations.

    Provides common functionality for message handling, transport management,
    and JSON-RPC protocol processing that's shared between client and server
    sessions.
    """

    def __init__(self, transport: Transport):
        self.transport = transport
        self._pending_requests: dict[
            str, tuple[Request, asyncio.Future[Result | Error]]
        ] = {}
        self._message_loop_task: asyncio.Task[None] | None = None
        self._in_flight_requests: dict[str | int, asyncio.Task[None]] = {}

    @property
    @abstractmethod
    def initialized(self) -> bool:
        """Return True if the session is initialized."""
        pass

    @property
    def running(self) -> bool:
        """True if the message loop is actively processing messages."""
        return (
            self._message_loop_task is not None and not self._message_loop_task.done()
        )

    async def start(self) -> None:
        """Start processing messages from the transport.

        Creates a background task that continuously reads and handles incoming
        messages until stop() is called. This is required before sending any
        requests or receiving notifications.

        Safe to call multiple times - subsequent calls are ignored if already running.

        Raises:
            ConnectionError: If the transport is closed or unavailable.
        """
        if self.running:
            return
        if not self.transport.is_open:
            raise ConnectionError("Cannot start session: transport is closed")

        self._message_loop_task = asyncio.create_task(self._message_loop())
        self._message_loop_task.add_done_callback(self._on_message_loop_done)

    async def stop(self) -> None:
        """Stop message processing and cancel pending requests.

        Cancels the background message processing task, resolves any pending
        requests, and cancels any in-flight request handlers.

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

        # Cancel any in-flight requests we are handling
        for task in self._in_flight_requests.values():
            task.cancel()
        self._in_flight_requests.clear()

    async def _message_loop(self) -> None:
        """Process incoming messages until cancelled or transport fails.

        Runs continuously in the background and hands off messages to the message
        handler. Individual message handling errors are logged and don't interrupt
        the loop, but transport failures will stop message processing entirely.
        """
        try:
            async for transport_message in self.transport.messages():
                try:
                    await self._handle_message(transport_message.payload)
                except Exception as e:
                    print(f"Error handling message: {e}")
                    continue
        except Exception as e:
            print(f"Transport error: {e}")

    def _on_message_loop_done(self, task: asyncio.Task[None]) -> None:
        """Clean up pending requests when the message loop exits."""
        for request, future in self._pending_requests.values():
            if not future.done():
                error = Error(
                    code=INTERNAL_ERROR,
                    message="Request failed. Session stopped.",
                )
                future.set_result(error)
        self._pending_requests.clear()

    async def _handle_message(
        self, payload: dict[str, Any] | list[dict[str, Any]]
    ) -> None:
        """Route messages to their handlers without blocking the session.

        Requests and notifications run as background tasks so they can't block
        responses or other message processing. Routing errors (like invalid
        message formats) propagate to the message loop for logging.

        Args:
            payload: JSON-RPC message(s) from the transport.

        Raises:
            ValueError: If the message is not a valid JSON-RPC message.

        Note:
            Routing errors bubble up to the message loop, while request/notification
            handlers catch their own errors since they run in the background.
        """
        if isinstance(payload, list):
            for item in payload:
                await self._handle_message(item)
            return

        if self._is_valid_response(payload):
            await self._handle_response(payload)
        elif self._is_valid_request(payload):
            task = asyncio.create_task(
                self._handle_request(payload),
                name=f"handle_request_{payload['id']}",
            )
            self._in_flight_requests[payload["id"]] = task
            task.add_done_callback(
                lambda t, request_id=payload["id"]: self._in_flight_requests.pop(
                    request_id, None
                )
            )
        elif self._is_valid_notification(payload):
            asyncio.create_task(
                self._handle_notification(payload),
                name=f"handle_notification_{payload['method']}",
            )
        else:
            raise ValueError(f"Unknown message type: {payload}")

    def _is_valid_response(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC response."""
        has_valid_id = payload.get("id") is not None and isinstance(
            payload.get("id"), int | str
        )
        has_result = "result" in payload
        has_error = "error" in payload
        has_exactly_one_response_field = has_result ^ has_error

        return has_valid_id and has_exactly_one_response_field

    def _is_valid_request(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC request."""
        has_valid_id = payload.get("id") is not None and isinstance(
            payload.get("id"), int | str
        )
        return "method" in payload and has_valid_id

    def _is_valid_notification(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a valid JSON-RPC notification."""
        return "method" in payload and "id" not in payload

    async def _handle_response(self, payload: dict[str, Any]) -> None:
        """Resolve a pending request with the peer's response.

        Matches response to original request by ID, parses into Result or Error,
        and resolves the waiting future.

        Args:
            payload: Validated JSON-RPC response.
        """
        message_id = payload["id"]

        if message_id in self._pending_requests:
            original_request, future = self._pending_requests.pop(message_id)
            result_or_error = self._parse_response(payload, original_request)
            future.set_result(result_or_error)
        else:
            print(f"Unmatched response for request ID {message_id}")

    # TODO: TEST THIS
    def _parse_response(
        self, payload: dict[str, Any], original_request: Request
    ) -> Result | Error:
        """Parse JSON-RPC response into typed Result or Error objects.

        If we can't parse the response, we return an error.

        Args:
            payload: Raw JSON-RPC response from peer.
            original_request: Request that triggered this response.

        Returns:
            Typed Result object for success, or Error object for failures.
        """
        if "result" in payload:
            try:
                result_type = original_request.expected_result_type()
                return result_type.from_protocol(payload)
            except Exception as e:
                return Error(
                    code=INTERNAL_ERROR,
                    message=f"Failed to parse {result_type.__name__} response",
                    data={
                        "expected_type": result_type.__name__,
                        "full_response": payload,
                        "parse_error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
        else:
            try:
                return Error.from_protocol(payload)
            except Exception as e:
                return Error(
                    code=INTERNAL_ERROR,
                    message="Failed to parse response",
                    data={
                        "full_response": payload,
                        "parse_error": str(e),
                        "error_type": type(e).__name__,
                    },
                )

    def _parse_notification(self, payload: dict[str, Any]) -> Notification | None:
        """Parse a JSON-RPC notification payload into a typed Notification object.

        Uses the NOTIFICATION_CLASSES registry to look up the appropriate notification
        class and deserialize the payload. Returns None for unknown notification types
        since notifications are fire-and-forget.

        Args:
            payload: Raw JSON-RPC notification payload.

        Returns:
            Typed Notification object on success, None for unknown types or parse
            failures.
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

    async def _handle_notification(self, payload: dict[str, Any]) -> None:
        """Process peer notifications, delegating to subclass implementations.

        Parses the notification payload and delegates to session-specific handlers.
        Handler exceptions are logged since notifications don't require responses.

        Args:
            payload: Raw JSON-RPC notification payload.

        Note:
            Runs as background task - exceptions won't be caught by the message loop.
        """
        # Parse the notification
        notification = self._parse_notification(payload)

        if notification is None:
            # Parsing failed or unknown notification - already logged
            return

        try:
            await self._handle_session_notification(notification)
        except Exception as e:
            print(f"Error handling notification {notification.method}: {e}")

    async def _handle_session_notification(self, notification: Notification) -> None:
        """Handle session-specific notifications. Override in subclasses."""
        print(f"Unhandled notification method: {notification.method}")

    def _parse_request(self, payload: dict[str, Any]) -> Request | Error:
        """Parse a JSON-RPC request payload into a typed Request object or Error.

        Uses the REQUEST_CLASSES registry to look up the appropriate request class
        and deserialize the payload. Returns an Error object for any parsing failures
        instead of raising exceptions.

        Args:
            payload: Raw JSON-RPC request payload.

        Returns:
            Typed Request object on success, or Error for parsing failures.
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

    async def _handle_request(self, payload: dict[str, Any]) -> None:
        """Process peer requests and send back responses.

        Parses the request payload, delegates business logic to subclass
        implementations, and provides defensive exception handling. Every request
        gets a response, even when handlers crash.

        Args:
            payload: Raw JSON-RPC request payload.

        Raises:
            ConnectionError: Transport failures during response sending.

        Note:
            Runs as background task - exceptions won't be caught by the message loop.
        """
        message_id = payload["id"]

        try:
            # Parse the request - returns Request or Error
            request_or_error = self._parse_request(payload)

            if isinstance(request_or_error, Error):
                # Parsing failed - send the error directly
                response = JSONRPCError.from_error(request_or_error, message_id)
            else:
                # Parsing succeeded - handle the request
                result_or_error = await self._handle_session_request(request_or_error)

                if isinstance(result_or_error, Result):
                    response = JSONRPCResponse.from_result(result_or_error, message_id)
                else:
                    response = JSONRPCError.from_error(result_or_error, message_id)

        except asyncio.CancelledError:
            error = Error(
                code=INTERNAL_ERROR, message=f"Request {message_id} cancelled"
            )
            response = JSONRPCError.from_error(error, message_id)
        except Exception:
            error = Error(
                code=INTERNAL_ERROR,
                message=f"Internal error processing request {message_id}",
            )
            response = JSONRPCError.from_error(error, message_id)

        await self.transport.send(response.to_wire())

    async def _handle_session_request(self, request: Request) -> Result | Error:
        """Handle session-specific requests (non-ping)."""
        raise UnknownRequestError(request.method)

    async def send_request(
        self,
        request: Request,
        timeout: float = 30.0,
    ) -> Result | Error:
        """Send a request to the peer and wait for its response.

        Generates request IDs, manages the request lifecycle, and handles timeouts.
        Responses are automatically cleaned up when received, while timeouts trigger
        manual cleanup and send cancellation notifications to the peer.

        The returned Result object is automatically typed based on the request type
        (e.g., InitializeRequest returns InitializeResult). This parsing happens
        in the response handler using the request's expected_result_type().

        Most requests require an initialized session. PingRequests work anytime since
        they test basic connectivity.

        Args:
            request: The MCP request to send
            timeout: How long to wait for a response (seconds)

        Returns:
            Peer's response as typed Result or Error object.

        Raises:
            RuntimeError: Session not initialized (client hasn't sent initialized
                notification)
            TimeoutError: Peer didn't respond in time
        """
        await self.start()
        if not self.initialized and not isinstance(
            request, (PingRequest, InitializeRequest)
        ):
            raise RuntimeError("Session must be initialized to send non-ping requests")

        # Generate request ID and create JSON-RPC wrapper
        request_id = str(uuid.uuid4())
        jsonrpc_request = JSONRPCRequest.from_request(request, request_id)

        future: asyncio.Future[Result | Error] = asyncio.Future()
        self._pending_requests[request_id] = (request, future)

        try:
            await self.transport.send(jsonrpc_request.to_wire())
            result = await asyncio.wait_for(future, timeout)
            return result
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)

            try:
                cancelled_notification = CancelledNotification(
                    request_id=request_id,
                    reason="Request timed out",
                )
                await self.send_notification(cancelled_notification)
            except Exception as e:
                print(f"Error sending cancellation notification: {e}")
            raise TimeoutError(f"Request {request_id} timed out after {timeout}s")

    async def send_notification(self, notification: Notification) -> None:
        """Send a notification to the peer."""
        await self.start()
        jsonrpc_notification = JSONRPCNotification.from_notification(notification)
        await self.transport.send(jsonrpc_notification.to_wire())

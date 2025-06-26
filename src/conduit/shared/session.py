"""Base session implementation shared between client and server."""

import asyncio
import uuid
from abc import ABC, abstractmethod
from typing import Any

from conduit.protocol.base import (
    INTERNAL_ERROR,
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
from conduit.protocol.unions import NOTIFICATION_REGISTRY
from conduit.shared.exceptions import UnknownNotificationError, UnknownRequestError
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
        self._running = False
        self.notifications: asyncio.Queue[Notification] = asyncio.Queue()

    async def start_message_loop(self) -> None:
        """Start the background message processing loop.

        Begins continuous processing of incoming messages from the transport.
        The loop handles JSON-RPC requests, responses, and notifications
        concurrently while the session remains active.

        Safe to call multiple times - subsequent calls are ignored if the
        loop is already running.

        Note: This only starts message processing. For clients, you'll still
        need to call initialize() to complete the MCP handshake.
        """
        if self._running:
            return
        self._running = True
        self._message_loop_task = asyncio.create_task(self._message_loop())

    async def send_request(
        self,
        request: Request,
        timeout: float = 30.0,
    ) -> Result | Error | None:
        """Send a request to the client and wait for its response.

        Handles the complete request lifecycle—generates IDs, manages
        timeouts, and cleans up automatically. Returns None for fire-and-forget
        requests.

        Most requests require an initialized session. PingRequests work anytime
        since they test basic connectivity.

        Args:
            request: The MCP request to send
            timeout: How long to wait for a response (seconds)

        Returns:
            Client's response, or None for requests that don't expect replies.

        Raises:
            RuntimeError: Session not initialized (client hasn't sent initialized
                notification)
            TimeoutError: Client didn't respond in time
        """
        await self.start_message_loop()
        await self._ensure_can_send_request(request)

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

    async def close(self) -> None:
        """Stop the message processing loop and clean up resources.

        Gracefully shuts down the session by:
        1. Stopping the background message loop
        2. Cancelling any pending requests with errors
        3. Closing the underlying transport connection

        Once stopped, the session cannot be restarted - create a new
        session to reconnect.

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
        for task in self._in_flight_requests.values():
            task.cancel()
        self._in_flight_requests.clear()

        await self.transport.close()

    async def send_notification(self, notification: Notification) -> None:
        """Send a notification to the peer."""
        await self.start_message_loop()
        jsonrpc_notification = JSONRPCNotification.from_notification(notification)
        await self.transport.send(jsonrpc_notification.to_wire())

    async def _message_loop(self) -> None:
        """Core message processing loop that runs in the background.

        Continuously reads messages from the transport and routes them
        to appropriate handlers. Handles three types of JSON-RPC messages:

        - Responses: Matched to pending requests by ID and resolved
        - Requests: Processed concurrently in separate tasks
        - Notifications: Parsed and queued for application consumption

        The loop is resilient to message handling errors but will terminate
        on transport failures. All pending requests are cancelled on exit.
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
        """Cancel all pending requests with a CancelledError."""
        for request_id, (request, future) in self._pending_requests.items():
            if not future.done():
                error = Error(
                    code=INTERNAL_ERROR,
                    message=f"{request.method} request cancelled because: {reason}",
                )
                future.set_result(error)
        self._pending_requests.clear()

    # TODO: Add cancellation documentation
    async def _handle_message(
        self, payload: dict[str, Any] | list[dict[str, Any]]
    ) -> None:
        """Route incoming JSON-RPC messages to appropriate handlers.
        NEEDS CANCELLATION DOCUMENTATION

        Central dispatch point that identifies message types and routes to:
        - _handle_response() for responses to our requests
        - _handle_request() for incoming requests (processed as tasks)
        - _handle_notification() for notifications

        Supports both single messages and batched message arrays.
        Individual message handling errors are logged but don't stop
        the message loop.

        Args:
            payload: Raw JSON-RPC message(s) from the transport.
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
                await self._handle_notification(payload)
            else:
                raise ValueError(f"Unknown message type: {payload}")
        except Exception as e:
            print("Error handling message", e)
            raise

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

        Args:
            payload: Raw JSON-RPC response from peer.
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

    # TODO: Clean up
    async def _handle_notification(self, payload: dict[str, Any]) -> None:
        """Parse notification and queue it for consumption."""
        method = payload["method"]
        notification_class = NOTIFICATION_REGISTRY.get(method)

        if notification_class is None:
            raise UnknownNotificationError(method)

        if method == "notifications/cancelled":
            notification = CancelledNotification.from_protocol(payload)
            if notification.request_id in self._in_flight_requests:
                self._in_flight_requests[notification.request_id].cancel()
            await self.notifications.put(notification)
            return

        notification = notification_class.from_protocol(payload)
        await self.notifications.put(notification)

    async def _handle_request(self, payload: dict[str, Any]) -> None:
        """Handle peer request and send back a response."""
        message_id = payload["id"]

        try:
            result_or_error = await self._handle_session_request(payload)

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

    @property
    @abstractmethod
    def initialized(self) -> bool:
        """Return True if the session is initialized."""
        pass

    @abstractmethod
    async def _handle_session_request(self, payload: dict[str, Any]) -> Result | Error:
        """Handle session-specific requests (non-ping)."""
        pass

    @abstractmethod
    async def _ensure_can_send_request(self, request: Request) -> None:
        """Verify the session can send this request.

        Raises:
            RuntimeError: If the session isn't in the right state for this request
        """
        pass

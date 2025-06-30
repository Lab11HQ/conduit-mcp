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
from conduit.protocol.common import CancelledNotification, PingRequest
from conduit.protocol.jsonrpc import (
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)
from conduit.protocol.unions import NOTIFICATION_REGISTRY
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
                    message="Request failed: Connection closed",
                )
                future.set_result(error)
        self._pending_requests.clear()

    async def _handle_message(
        self, payload: dict[str, Any] | list[dict[str, Any]]
    ) -> None:
        """Route messages to their handlers without blocking the session.

        Requests and notifications run as background tasks so they can't block
        responses or other message processing.

        Args:
            payload: JSON-RPC message(s) from the transport.
        """
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
                asyncio.create_task(
                    self._handle_notification(payload),
                    name=f"handle_notification_{payload['method']}",
                )
            else:
                raise ValueError(f"Unknown message type: {payload}")
        except Exception as e:
            print(f"Error handling message: {e}")

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

    def _parse_response(
        self, payload: dict[str, Any], original_request: Request
    ) -> Result | Error:
        """Parse JSON-RPC response into typed Result or Error objects.

        Args:
            payload: Raw JSON-RPC response from peer.
            original_request: Request that triggered this response.

        Returns:
            Typed Result object for success, or Error object for failures.
        """
        if "result" in payload:
            result_type = original_request.expected_result_type()
            return result_type.from_protocol(payload)
        return Error.from_protocol(payload)

    async def _handle_notification(self, payload: dict[str, Any]) -> None:
        """Parse notification and queue it for consumption."""
        method = payload["method"]
        notification_class = NOTIFICATION_REGISTRY.get(method)

        if notification_class is None:
            print(f"Unknown notification method: {method}")
            return

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

        except asyncio.CancelledError:
            error = Error(
                code=INTERNAL_ERROR,
                message=f"Request {message_id} cancelled by client",
            )
            error_response = JSONRPCError.from_error(error, message_id)
            await self.transport.send(error_response.to_wire())

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
                code=INTERNAL_ERROR,
                message=f"Internal error processing request {message_id}",
            )
            error_response = JSONRPCError.from_error(error, message_id)
            await self.transport.send(error_response.to_wire())

    async def _handle_session_request(self, payload: dict[str, Any]) -> Result | Error:
        """Handle session-specific requests (non-ping)."""
        method = payload.get("method", "unknown")
        raise UnknownRequestError(method)

    async def send_request(
        self,
        request: Request,
        timeout: float = 30.0,
    ) -> Result | Error | None:
        """Send a request to the peer and wait for its response.

        Generates request IDs, manages the request lifecycle, and handles
        timeouts. Successful responses are cleaned up by the response handler,
        while timeouts are cleaned up here.

        Most requests require an initialized session. PingRequests work anytime
        since they test basic connectivity.

        Args:
            request: The MCP request to send
            timeout: How long to wait for a response (seconds)

        Returns:
            Peer's response as Result or Error object.

        Raises:
            RuntimeError: Session not initialized (client hasn't sent initialized
                notification)
            TimeoutError: Peer didn't respond in time
        """
        await self.start()
        if not self.initialized and not isinstance(request, PingRequest):
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

"""Base session implementation shared between client and server."""

import asyncio
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
from conduit.protocol.common import EmptyResult
from conduit.protocol.jsonrpc import JSONRPCError, JSONRPCNotification, JSONRPCResponse
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
        self._running = False
        self.notifications: asyncio.Queue[Notification] = asyncio.Queue()

    async def start_message_loop(self) -> None:
        """Start the background message loop if not already running."""
        if self._running:
            return
        self._running = True
        self._message_loop_task = asyncio.create_task(self._message_loop())

    async def stop_message_loop(self) -> None:
        """Stop the session and clean up all resources."""
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

        await self.transport.close()

    async def send_notification(self, notification: Notification) -> None:
        """Send a notification to the peer."""
        await self.start_message_loop()
        jsonrpc_notification = JSONRPCNotification.from_notification(notification)
        await self.transport.send(jsonrpc_notification.to_wire())

    async def _message_loop(self) -> None:
        """Process incoming messages until the session stops."""
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

    async def _handle_message(
        self, payload: dict[str, Any] | list[dict[str, Any]]
    ) -> None:
        """Route incoming messages to the appropriate handler."""
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

    async def _handle_notification(self, payload: dict[str, Any]) -> None:
        """Parse notification and queue it for consumption."""
        notification = self._parse_notification(payload)
        await self.notifications.put(notification)

    def _parse_notification(self, payload: dict[str, Any]) -> Notification:
        """Parse JSON-RPC notification into typed notification object."""
        method = payload["method"]
        notification_class = self._get_supported_notifications().get(method)
        if notification_class is None:
            raise UnknownNotificationError(method)
        return notification_class.from_protocol(payload)

    async def _handle_request(self, payload: dict[str, Any]) -> None:
        """Handle peer request and send back a response."""
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
        """Parse JSON-RPC request into typed request object."""
        method = payload["method"]
        request_class = self._get_supported_requests().get(method)
        if request_class is None:
            raise UnknownRequestError(method)
        return request_class.from_protocol(payload)

    async def _route_request(self, request: Request) -> Result | Error:
        """Route request to the appropriate handler method."""
        # All sessions support ping
        if request.method == "ping":
            return await self._handle_ping(request)

        # Delegate to subclass for other methods
        return await self._handle_peer_request(request)

    async def _handle_ping(self, request: Request) -> Result:
        """Handle peer ping request."""
        return EmptyResult()

    @property
    @abstractmethod
    def initialized(self) -> bool:
        """Return True if the session is initialized."""
        pass

    @abstractmethod
    def _get_supported_notifications(self) -> dict[str, type[Notification]]:
        """Return the notification class registry for this session type."""
        pass

    @abstractmethod
    def _get_supported_requests(self) -> dict[str, type[Request]]:
        """Return the request class registry for this session type."""
        pass

    @abstractmethod
    async def _handle_peer_request(self, request: Request) -> Result | Error:
        """Handle session-specific requests (non-ping)."""
        pass

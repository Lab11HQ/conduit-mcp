"""Message processing mechanics for client sessions.

Handles the message loop, routing, and parsing while keeping
the session focused on protocol logic rather than message processing.
"""

import asyncio
from typing import Any, Awaitable, Callable, TypeVar

from conduit.client.server_manager import ServerManager
from conduit.protocol.base import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    Error,
    Notification,
    Request,
    Result,
)
from conduit.protocol.jsonrpc import JSONRPCError, JSONRPCResponse
from conduit.shared.message_parser import MessageParser
from conduit.transport.client import ClientTransport

TRequest = TypeVar("TRequest", bound=Request)
TResult = TypeVar("TResult", bound=Result)
TNotification = TypeVar("TNotification", bound=Notification)


RequestHandler = Callable[[TRequest], Awaitable[TResult | Error]]
NotificationHandler = Callable[[TNotification], Awaitable[None]]


class ClientMessageCoordinator:
    """Coordinates all message flow for client sessions.

    Handles bidirectional message coordination: routes inbound requests/notifications
    from server, sends outbound requests to server, and manages response tracking.
    Keeps the session focused on protocol logic.
    """

    def __init__(self, transport: ClientTransport, server_manager: ServerManager):
        self.transport = transport
        self.server_manager = server_manager
        self.parser = MessageParser()
        self._request_handlers: dict[str, RequestHandler] = {}
        self._notification_handlers: dict[str, NotificationHandler] = {}
        self._message_loop_task: asyncio.Task[None] | None = None

    # ================================
    # Lifecycle
    # ================================

    @property
    def running(self) -> bool:
        """True if the message loop is actively processing messages."""
        return (
            self._message_loop_task is not None and not self._message_loop_task.done()
        )

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
            raise ConnectionError("Cannot start coordinator: transport is closed")

        self._message_loop_task = asyncio.create_task(self._message_loop())
        self._message_loop_task.add_done_callback(self._on_message_loop_done)

    async def stop(self) -> None:
        """Stop message processing and clean up all incoming and outgoing requests.

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

        self.server_manager.cleanup_requests()

    # ================================
    # Message loop
    # ================================

    async def _message_loop(self) -> None:
        """Process incoming messages until cancelled or transport fails.

        Runs continuously in the background and hands off messages to the message
        handler. Individual message handling errors are logged and don't interrupt
        the loop, but transport failures will stop message processing entirely.
        """
        try:
            async for server_message in self.transport.server_messages():
                try:
                    await self._handle_server_message(server_message)
                except Exception as e:
                    print(f"Error handling message: {e}")
                    continue
        except Exception as e:
            print(f"Transport error: {e}")

    def _on_message_loop_done(self, task: asyncio.Task[None]) -> None:
        """Clean up when message loop task completes.

        Called whenever the message loop task finishes - whether due to normal
        completion, cancellation, or unexpected errors. Ensures proper cleanup
        of coordinator state.
        """
        self._message_loop_task = None
        self.server_manager.cleanup_requests()

    # ================================
    # Route messages
    # ================================

    async def _handle_server_message(self, payload: dict[str, Any]) -> None:
        """Route server message to appropriate handler."""
        if self.parser.is_valid_request(payload):
            await self._handle_request(payload)
        elif self.parser.is_valid_notification(payload):
            await self._handle_notification(payload)
        elif self.parser.is_valid_response(payload):
            await self._handle_response(payload)
        else:
            print(f"Unknown message type: {payload}")

    # ================================
    # Handle requests
    # ================================

    async def _handle_request(self, payload: dict[str, Any]) -> None:
        """Handle an incoming request from the server."""
        request_id = payload["id"]

        request_or_error = self.parser.parse_request(payload)

        if isinstance(request_or_error, Error):
            await self._send_error(request_id, request_or_error)
            return

        await self._route_request(request_id, request_or_error)

    async def _route_request(
        self,
        request_id: str | int,
        request: Request,
    ) -> None:
        """Route request to appropriate handler and execute it."""
        handler = self._request_handlers.get(request.method)
        if not handler:
            error = Error(
                code=METHOD_NOT_FOUND,
                message=f"No handler for method: {request.method}",
            )
            await self._send_error(request_id, error)
            return

        task = asyncio.create_task(
            self._execute_request_handler(handler, request_id, request),
            name=f"handle_{request.method}_{request_id}",
        )

        self.server_manager.track_request_from_server(request_id, request, task)
        task.add_done_callback(
            lambda t: self.server_manager.remove_request_from_server(request_id)
        )

    async def _execute_request_handler(
        self,
        handler: RequestHandler,
        request_id: str | int,
        request: Request,
    ) -> None:
        """Execute handler and send response back to server."""
        try:
            result_or_error = await handler(request)

            if isinstance(result_or_error, Error):
                response = JSONRPCError.from_error(result_or_error, request_id)
            else:
                response = JSONRPCResponse.from_result(result_or_error, request_id)

            await self.transport.send_to_server(response.to_wire())

        except Exception:
            error = Error(
                code=INTERNAL_ERROR,
                message="Problem handling request",
                data={"request": request},
            )
            await self._send_error(request_id, error)

    # ================================
    # Handle notifications
    # ================================

    async def _handle_notification(self, payload: dict[str, Any]) -> None:
        """Parse and route typed notification to handler."""
        method = payload["method"]

        notification = self.parser.parse_notification(payload)
        if notification is None:
            return

        handler = self._notification_handlers.get(method)
        if not handler:
            print(f"Unknown notification '{method}' from server")
            return

        asyncio.create_task(
            handler(notification),
            name=f"handle_{method}",
        )

    # ================================
    # Cancel requests
    # ================================

    async def cancel_request_from_server(self, request_id: str | int) -> bool:
        """Cancel a request from the server."""
        result = self.server_manager.remove_request_from_server(request_id)
        if result is None:
            return False
        request, task = result
        return task.cancel()

    # ================================
    # Register handlers
    # ================================

    def register_request_handler(self, method: str, handler: RequestHandler) -> None:
        """Register a request handler."""
        self._request_handlers[method] = handler

    def register_notification_handler(
        self, method: str, handler: NotificationHandler
    ) -> None:
        """Register a notification handler."""
        self._notification_handlers[method] = handler

    # ================================
    # Helpers
    # ================================
    async def _send_error(self, request_id: str | int, error: Error) -> None:
        """Send error response to server."""
        response = JSONRPCError.from_error(error, request_id)
        await self.transport.send_to_server(response.to_wire())

"""Message processing mechanics for client sessions.

Handles the message loop, routing, and parsing while keeping
the session focused on protocol logic rather than message processing.
"""

import asyncio
import logging
import uuid
from collections.abc import Coroutine
from typing import Any, Awaitable, Callable, TypeVar

from conduit.client.request_context import RequestContext
from conduit.client.server_manager import ServerManager
from conduit.protocol.base import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    Error,
    Notification,
    Request,
    Result,
)
from conduit.protocol.common import CancelledNotification
from conduit.protocol.initialization import InitializeRequest
from conduit.protocol.jsonrpc import (
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)
from conduit.shared.message_parser import MessageParser
from conduit.transport.client_v2 import ClientTransport, ServerMessage

TRequest = TypeVar("TRequest", bound=Request)
TResult = TypeVar("TResult", bound=Result)
TNotification = TypeVar("TNotification", bound=Notification)

RequestHandler = Callable[[RequestContext, TRequest], Awaitable[TResult | Error]]
NotificationHandler = Callable[
    [RequestContext, TNotification], Coroutine[Any, Any, None]
]


class MessageCoordinator:
    """Coordinates all message flow for client sessions.

    Handles bidirectional message coordination: routes inbound requests/notifications
    from server, sends outbound requests to server, and enriches incoming messages with
    server context.
    """

    def __init__(self, transport: ClientTransport, server_manager: ServerManager):
        self.transport = transport
        self.server_manager = server_manager
        self.parser = MessageParser()
        self._request_handlers: dict[str, RequestHandler] = {}
        self._notification_handlers: dict[str, NotificationHandler] = {}
        self._message_loop_task: asyncio.Task[None] | None = None
        self.logger = logging.getLogger("conduit.client.coordinator")

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
        """
        if self.running:
            return

        self._message_loop_task = asyncio.create_task(self._message_loop())
        self._message_loop_task.add_done_callback(self._on_message_loop_done)

    async def stop(self) -> None:
        """Stop message processing and clean up all requests.

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

        self.server_manager.cleanup_all_servers()

    # ================================
    # Message loop
    # ================================

    async def _message_loop(self) -> None:
        """Processes incoming messages until cancelled or transport fails.

        Runs continuously in the background and hands off messages to handlers.
        Individual message handling errors are logged and don't interrupt the loop,
        but transport failures will stop message processing entirely.
        """
        try:
            async for server_message in self.transport.server_messages():
                try:
                    await self._route_server_message(server_message)
                except Exception as e:
                    self.logger.warning(
                        f"Error handling message from {server_message.server_id}: {e}"
                    )
                    continue
        except Exception as e:
            self.logger.error(f"Transport error: {e}")

    def _on_message_loop_done(self, task: asyncio.Task[None]) -> None:
        """Cleans up when message loop task completes.

        Called whenever the message loop task finishes - ensures proper cleanup of
        coordinator state.
        """
        self._message_loop_task = None
        self.server_manager.cleanup_all_servers()

    # ================================
    # Build context
    # ================================

    def _build_context(self, server_id: str) -> RequestContext:
        """Builds context for a request.

        Args:
            server_id: ID of the server making the request

        Returns:
            RequestContext: Context with server state and helpers

        Raises:
            ValueError: If the server is not registered with the client
        """
        server_state = self.server_manager.get_server(server_id)
        if server_state is None:
            raise ValueError(f"Server {server_id} not registered")

        return RequestContext(
            server_id=server_id,
            server_state=server_state,
            server_manager=self.server_manager,
            transport=self.transport,
        )

    # ================================
    # Route messages
    # ================================

    async def _route_server_message(self, server_message: ServerMessage) -> None:
        """Routes an incoming message to the appropriate handler.

        Args:
            server_message: Message from server with ID and payload
        """
        payload = server_message.payload
        server_id = server_message.server_id

        if self.parser.is_valid_request(payload):
            await self._handle_request(server_id, payload)
        elif self.parser.is_valid_notification(payload):
            await self._handle_notification(server_id, payload)
        elif self.parser.is_valid_response(payload):
            await self._handle_response(server_id, payload)
        else:
            self.logger.warning(f"Unknown message type from {server_id}: {payload}")

    # ================================
    # Handle requests
    # ================================

    async def _handle_request(self, server_id: str, payload: dict[str, Any]) -> None:
        """Parses and routes an incoming request from the server."""
        request_id = payload["id"]

        request_or_error = self.parser.parse_request(payload)

        if isinstance(request_or_error, Error):
            await self._send_error(server_id, request_id, request_or_error)
            return

        await self._route_request(server_id, request_id, request_or_error)

    async def _route_request(
        self,
        server_id: str,
        request_id: str | int,
        request: Request,
    ) -> None:
        """Routes an incoming request to the appropriate handler.

        Creates request context and tracks request.

        Args:
            server_id: ID of the server that sent the request
            request_id: ID of the request
            request: The request object
        """
        handler = self._request_handlers.get(request.method)
        if not handler:
            error = Error(
                code=METHOD_NOT_FOUND,
                message=f"No handler for method: {request.method}",
            )
            await self._send_error(server_id, request_id, error)
            return

        try:
            context = self._build_context(server_id)
        except ValueError as e:
            error = Error(
                code=INTERNAL_ERROR,
                message="Server not registered. Can't build context.",
            )
            await self._send_error(server_id, request_id, error)
            self.logger.warning(f"Failed to build request context for {server_id}: {e}")
            return

        task = asyncio.create_task(
            self._execute_request_handler(handler, context, request_id, request),
            name=f"handle_{request.method}_{request_id}",
        )

        self.server_manager.track_request_from_server(
            server_id, request_id, request, task
        )
        task.add_done_callback(
            lambda t: self.server_manager.remove_request_from_server(
                server_id, request_id
            )
        )

    async def _execute_request_handler(
        self,
        handler: RequestHandler,
        context: RequestContext,
        request_id: str | int,
        request: Request,
    ) -> None:
        """Executes handler and sends response back to server."""
        try:
            result_or_error = await handler(context, request)

            if isinstance(result_or_error, Error):
                response = JSONRPCError.from_error(result_or_error, request_id)
            else:
                response = JSONRPCResponse.from_result(result_or_error, request_id)

            await self.transport.send(context.server_id, response.to_wire())

        except Exception:
            error = Error(
                code=INTERNAL_ERROR,
                message="Request handler failed",
                data={"request": request},
            )
            await self._send_error(context.server_id, request_id, error)

    # ================================
    # Handle notifications
    # ================================

    async def _handle_notification(
        self, server_id: str, payload: dict[str, Any]
    ) -> None:
        """Parses and routes an incoming notification from the server."""
        notification = self.parser.parse_notification(payload)
        if notification is None:
            return

        await self._route_notification(server_id, notification)

    async def _route_notification(
        self,
        server_id: str,
        notification: Notification,
    ) -> None:
        """Routes an incoming notification to the appropriate handler.

        Creates request context. Fails silently if we can't build the context.

        Args:
            server_id: ID of the server that sent the notification
            notification: The notification object
        """
        handler = self._notification_handlers.get(notification.method)
        if not handler:
            self.logger.info(f"No handler for notification: {notification.method}")
            return

        try:
            context = self._build_context(server_id)
        except ValueError as e:
            self.logger.warning(
                f"Failed to build context for {notification.method} notification "
                f"from {server_id}: {e}"
            )
            return

        task = asyncio.create_task(
            handler(context, notification),
            name=f"notify_{notification.method}_{server_id}",
        )

        task.add_done_callback(self._on_notification_done)

    def _on_notification_done(self, task: asyncio.Task[None]) -> None:
        """Handle completed notification tasks."""
        if task.exception():
            self.logger.exception(f"Notification handler failed: {task.exception()}")

    # ================================
    # Handle responses
    # ================================

    async def _handle_response(self, server_id: str, payload: dict[str, Any]) -> None:
        """Matches a response to a pending request and resolves it.

        Fulfills the waiting future if the response is for a known request.
        Logs an error if the response is for an unknown request.

        Args:
            server_id: ID of the server that sent the response
            payload: The response payload
        """
        request_id = payload["id"]

        request_future_tuple = self.server_manager.get_request_to_server(
            server_id, request_id
        )
        if not request_future_tuple:
            self.logger.warning(f"No pending request {request_id} from {server_id}")
            return

        original_request, future = request_future_tuple

        result_or_error = self.parser.parse_response(payload, original_request)

        self.server_manager.resolve_request_to_server(
            server_id, request_id, result_or_error
        )

    # ================================
    # Cancel requests from server
    # ================================

    async def cancel_request_from_server(
        self, server_id: str, request_id: str | int
    ) -> None:
        """Cancel a request from the server if it's still pending.

        Args:
            server_id: Server identifier
            request_id: Request identifier to cancel
        """
        self.server_manager.cancel_request_from_server(server_id, request_id)

    # ================================
    # Send requests to server
    # ================================

    async def send_request(
        self, server_id: str, request: Request, timeout: float = 30.0
    ) -> Result | Error:
        """Send a request to the server and wait for a response.

        Handles timeouts with automatic cancellation except for initialization
        requests.

        Args:
            request: The request object to send
            timeout: Maximum time to wait for response in seconds

        Returns:
            Result | Error: The server's response or timeout error

        Raises:
            RuntimeError: If coordinator is not running
            TimeoutError: If server doesn't respond within timeout
        """
        if not self.running:
            raise RuntimeError("Cannot send request: coordinator is not running")

        request_id = str(uuid.uuid4())
        jsonrpc_request = JSONRPCRequest.from_request(request, request_id)
        future: asyncio.Future[Result | Error] = asyncio.Future()

        self.server_manager.track_request_to_server(
            server_id, request_id, request, future
        )

        try:
            await self.transport.send(server_id, jsonrpc_request.to_wire())
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            await self._handle_request_timeout(server_id, request_id, request)
            raise
        finally:
            self.server_manager.remove_request_to_server(server_id, request_id)

    async def _handle_request_timeout(
        self, server_id: str, request_id: str, request: Request
    ) -> None:
        """Sends a cancellation notification to a server.

        Note: Won't try to cancel initialization requests.
        """
        if isinstance(request, InitializeRequest):
            return
        try:
            cancelled_notification = CancelledNotification(
                request_id=request_id,
                reason="Request timed out",
            )
            await self.send_notification(server_id, cancelled_notification)
        except Exception as e:
            self.logger.error(
                f"Error sending cancellation to server {server_id}: {e}. "
                f"Request: {request}"
            )

    # ================================
    # Send notifications
    # ================================

    async def send_notification(
        self, server_id: str, notification: Notification
    ) -> None:
        """Send a notification to the server.

        Raises:
            RuntimeError: If coordinator is not running
        """
        if not self.running:
            raise RuntimeError("Cannot send notification: coordinator is not running")

        jsonrpc_notification = JSONRPCNotification.from_notification(notification)
        await self.transport.send(server_id, jsonrpc_notification.to_wire())

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
    async def _send_error(
        self, server_id: str, request_id: str | int, error: Error
    ) -> None:
        """Send error response to server."""
        response = JSONRPCError.from_error(error, request_id)
        await self.transport.send(server_id, response.to_wire())

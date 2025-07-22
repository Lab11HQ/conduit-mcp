"""Message processing mechanics for server sessions.

Handles the message loop, routing, and parsing while keeping
the session focused on protocol logic rather than message processing.
"""

import asyncio
import logging
import uuid
from collections.abc import Coroutine
from typing import Any, Awaitable, Callable, TypeVar

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
from conduit.server.client_manager import ClientManager
from conduit.server.request_context import RequestContext
from conduit.shared.message_parser import MessageParser
from conduit.transport.server import ClientMessage, ServerTransport

TRequest = TypeVar("TRequest", bound=Request)
TResult = TypeVar("TResult", bound=Result)
TNotification = TypeVar("TNotification", bound=Notification)

RequestHandler = Callable[[RequestContext, TRequest], Awaitable[TResult | Error]]
NotificationHandler = Callable[
    [RequestContext, TNotification], Coroutine[Any, Any, None]
]


class MessageCoordinator:
    """Coordinates all message flow for server sessions.

    Handles bidirectional message coordination: routes inbound requests/notifications
    from clients, sends outbound requests to clients, and manages response tracking.
    Keeps the session focused on protocol logic.
    """

    def __init__(self, transport: ServerTransport, client_manager: ClientManager):
        self.transport = transport
        self.client_manager = client_manager
        self.parser = MessageParser()
        self._request_handlers: dict[str, RequestHandler] = {}
        self._notification_handlers: dict[str, NotificationHandler] = {}
        self._message_loop_task: asyncio.Task[None] | None = None
        self.logger = logging.getLogger("conduit.server.coordinator")

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

        self.client_manager.cleanup_all_clients()

    # ================================
    # Message loop
    # ================================

    async def _message_loop(self) -> None:
        """Processes incoming client messages until cancelled or transport fails.

        Runs continuously in the background and hands off messages to registered
        handlers. Individual message handling errors are logged and don't interrupt
        the loop, but transport failures will stop message processing entirely.
        """
        try:
            async for client_message in self.transport.client_messages():
                try:
                    await self._route_client_message(client_message)
                except Exception as e:
                    self.logger.warning(
                        f"Error handling message from {client_message.client_id}: {e}"
                    )
                    continue
        except Exception as e:
            self.logger.error(f"Transport error: {e}")

    def _on_message_loop_done(self, task: asyncio.Task[None]) -> None:
        """Cleans up when message loop task completes.

        Called whenever the message loop task finishes - whether due to normal
        completion, cancellation, or unexpected errors. Ensures proper cleanup
        of coordinator state.
        """
        self._message_loop_task = None

        self.client_manager.cleanup_all_clients()

    # ================================
    # Build context
    # ================================

    def _build_context(self, client_id: str) -> RequestContext:
        """Builds context for a request.

        Args:
            client_id: ID of the client making the request

        Returns:
            RequestContext: Rich context with client state and helpers

        Raises:
            ValueError: If client is not registered
        """
        client_state = self.client_manager.get_client(client_id)
        if client_state is None:
            raise ValueError(f"Client {client_id} not registered")

        return RequestContext(
            client_id=client_id,
            client_state=client_state,
            client_manager=self.client_manager,
            transport=self.transport,
        )

    # ================================
    # Route messages
    # ================================

    async def _route_client_message(self, client_message: ClientMessage) -> None:
        """Routes an incoming message to the appropriate handler.

        Args:
            client_message: Message from client with ID and payload
        """
        payload = client_message.payload
        client_id = client_message.client_id

        if self.parser.is_valid_request(payload):
            await self._handle_request(client_id, payload)
        elif self.parser.is_valid_notification(payload):
            await self._handle_notification(client_id, payload)
        elif self.parser.is_valid_response(payload):
            await self._handle_response(client_id, payload)
        else:
            self.logger.info(f"Unknown message type from {client_id}: {payload}")

    # ================================
    # Handle requests
    # ================================

    async def _handle_request(self, client_id: str, payload: dict[str, Any]) -> None:
        """Handles an incoming request from a client."""
        request_id = payload["id"]

        self._ensure_client_registered(client_id)

        request_or_error = self.parser.parse_request(payload)

        if isinstance(request_or_error, Error):
            await self._send_error(client_id, request_id, request_or_error)
            return

        await self._route_request(client_id, request_id, request_or_error)

    async def _route_request(
        self,
        client_id: str,
        request_id: str | int,
        request: Request,
    ) -> None:
        """Routes an incoming request to the appropriate handler.

        Creates request context and tracks request.

        Args:
            client_id: ID of the client that sent the request
            request_id: ID of the request
            request: The request object
        """
        handler = self._request_handlers.get(request.method)
        if not handler:
            error = Error(
                code=METHOD_NOT_FOUND,
                message=f"No handler for method: {request.method}",
            )
            await self._send_error(client_id, request_id, error)
            return

        try:
            context = self._build_context(client_id)
        except ValueError as e:
            error = Error(
                code=INTERNAL_ERROR,
                message="Client not registered. Can't build context.",
            )
            await self._send_error(client_id, request_id, error)
            self.logger.warning(f"Failed to build request context for {client_id}: {e}")
            return

        task = asyncio.create_task(
            self._execute_request_handler(handler, context, request_id, request),
            name=f"handle_{request.method}_{client_id}_{request_id}",
        )

        self.client_manager.track_request_from_client(
            client_id, request_id, request, task
        )
        task.add_done_callback(
            lambda t: self.client_manager.remove_request_from_client(
                client_id, request_id
            )
        )

    async def _execute_request_handler(
        self,
        handler: RequestHandler,
        context: RequestContext,
        request_id: str | int,
        request: Request,
    ) -> None:
        """Executes handler and sends response back to client."""
        try:
            result_or_error = await handler(context, request)

            if isinstance(result_or_error, Error):
                response = JSONRPCError.from_error(result_or_error, request_id)
            else:
                response = JSONRPCResponse.from_result(result_or_error, request_id)

            await self.transport.send(context.client_id, response.to_wire())

        except Exception as e:
            self.logger.exception(
                f"Handler failed for {request.method} from {context}: {e}"
            )
            error = Error(
                code=INTERNAL_ERROR,
                message=f"Handler execution failed: {str(e)}",
            )
            response = JSONRPCError.from_error(error, request_id)
            await self.transport.send(context.client_id, response.to_wire())

    # ================================
    # Handle notifications
    # ================================

    async def _handle_notification(
        self, client_id: str, payload: dict[str, Any]
    ) -> None:
        """Parses and routes an incoming notification to the appropriate handler."""
        notification = self.parser.parse_notification(payload)
        if notification is None:
            return

        await self._route_notification(client_id, notification)

    async def _route_notification(
        self,
        client_id: str,
        notification: Notification,
    ) -> None:
        """Routes an incoming notification to the appropriate handler.

        Creates request context. Fails silently if we can't build the context.

        Args:
            client_id: ID of the client that sent the notification
            notification: The notification object
        """
        handler = self._notification_handlers.get(notification.method)
        if not handler:
            self.logger.info(f"No handler for notification: {notification.method}")
            return

        # Build context for notification
        try:
            context = self._build_context(client_id)
        except ValueError as e:
            self.logger.warning(
                f"Failed to build context for {notification.method} notification "
                f"from {client_id}: {e}"
            )
            return

        task = asyncio.create_task(
            handler(context, notification),
            name=f"notify_{notification.method}_{client_id}",
        )

        task.add_done_callback(self._on_notification_done)

    def _on_notification_done(self, task: asyncio.Task[None]) -> None:
        """Handles completed notification tasks.

        Logs an error if the notification handler fails.
        """
        if task.exception():
            self.logger.exception(f"Notification handler failed: {task.exception()}")

    # ================================
    # Handle responses
    # ================================

    async def _handle_response(self, client_id: str, payload: dict[str, Any]) -> None:
        """Matches an incoming response to a pending request.

        Fulfills the waiting future if the response is for a known request.
        Logs an error if the response is for an unknown request.

        Args:
            client_id: ID of the client that sent the response
            payload: The response payload
        """
        request_id = payload["id"]

        request_future_tuple = self.client_manager.get_request_to_client(
            client_id, request_id
        )
        if not request_future_tuple:
            self.logger.warning(
                f"No pending request {request_id} for client {client_id}"
            )
            return

        original_request, future = request_future_tuple

        result_or_error = self.parser.parse_response(payload, original_request)

        self.client_manager.resolve_request_to_client(
            client_id, request_id, result_or_error
        )

    # ================================
    # Cancel requests from client
    # ================================

    async def cancel_request_from_client(
        self, client_id: str, request_id: str | int
    ) -> None:
        """Cancel a specific request from a client.

        Args:
            client_id: Client identifier
            request_id: Request identifier to cancel
        """
        self.client_manager.cancel_request_from_client(client_id, request_id)

    # ================================
    # Send requests
    # ================================

    async def send_request(
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
            RuntimeError: If coordinator is not running
            ConnectionError: Transport fails to send request
            TimeoutError: If client doesn't respond within timeout
        """
        if not self.running:
            raise RuntimeError("Cannot send request: coordinator is not running")

        # Prepare the request
        request_id = str(uuid.uuid4())
        jsonrpc_request = JSONRPCRequest.from_request(request, request_id)
        future: asyncio.Future[Result | Error] = asyncio.Future()

        # Set up tracking
        self._ensure_client_registered(client_id)
        self.client_manager.track_request_to_client(
            client_id, request_id, request, future
        )

        try:
            await self.transport.send(client_id, jsonrpc_request.to_wire())
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            await self._handle_request_timeout(client_id, request_id)
            raise
        finally:
            self.client_manager.remove_request_to_client(client_id, request_id)

    async def _handle_request_timeout(self, client_id: str, request_id: str) -> None:
        """Cleans up and notifies client when request times out."""

        try:
            cancelled_notification = CancelledNotification(
                request_id=request_id,
                reason="Request timed out",
            )
            await self.send_notification(client_id, cancelled_notification)
        except Exception as e:
            self.logger.warning(f"Error sending cancellation to {client_id}: {e}")

    # ================================
    # Send notifications
    # ================================

    async def send_notification(
        self, client_id: str, notification: Notification
    ) -> None:
        """Send a notification to a specific client.

        Args:
            client_id: ID of the client to send the notification to
            notification: The notification object to send

        Raises:
            RuntimeError: If coordinator is not running
        """
        if not self.running:
            raise RuntimeError("Cannot send notification: coordinator is not running")

        jsonrpc_notification = JSONRPCNotification.from_notification(notification)
        await self.transport.send(client_id, jsonrpc_notification.to_wire())

    # ================================
    # Register handlers
    # ================================

    def register_request_handler(self, method: str, handler: RequestHandler) -> None:
        """Register a handler for a specific method.

        Args:
            method: MCP method name (e.g., "tools/list")
            handler: Async function that takes (client_id, typed_request) and handles it
        """
        self._request_handlers[method] = handler

    def register_notification_handler(
        self, method: str, handler: NotificationHandler
    ) -> None:
        """Register a handler for a specific method.

        Args:
            method: MCP method name (e.g., "notifications/cancelled")
            handler: Async function that takes (client_id, typed_notification) and
                handles it
        """
        self._notification_handlers[method] = handler

    # ================================
    # Helpers
    # ================================

    def _ensure_client_registered(self, client_id: str) -> None:
        """Ensures client is registered with the client manager."""
        if not self.client_manager.get_client(client_id):
            self.client_manager.register_client(client_id)

    async def _send_error(
        self, client_id: str, request_id: str | int, error: Error
    ) -> None:
        """Sends error response to client."""
        response = JSONRPCError.from_error(error, request_id)
        await self.transport.send(client_id, response.to_wire())

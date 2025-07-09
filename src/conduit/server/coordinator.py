"""Message processing mechanics for server sessions.

Handles the message loop, routing, and parsing while keeping
the session focused on protocol logic rather than message processing.
"""

import asyncio
import uuid
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
from conduit.shared.message_parser import MessageParser
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

    def __init__(self, transport: ServerTransport, client_manager: ClientManager):
        self.transport = transport
        self.client_manager = client_manager
        self.parser = MessageParser()  # Add this line
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
            raise ConnectionError("Cannot start processor: transport is closed")

        self._message_loop_task = asyncio.create_task(self._message_loop())
        self._message_loop_task.add_done_callback(self._on_message_loop_done)

    async def stop(self) -> None:
        """Stop message processing and cancel in-flight requests.

        Cancels the background message processing task and any in-flight
        request handlers across all clients.

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

    def _on_message_loop_done(self, task: asyncio.Task[None]) -> None:
        """Clean up when message loop exits unexpectedly.

        Called when the message loop task completes due to transport failure
        or other unexpected errors (not normal stop() cancellation).
        """
        # Clear task reference so running becomes False
        self._message_loop_task = None

        # Clean up all client state - cancel in-flight requests and
        # resolve pending requests with errors
        self.client_manager.cleanup_all_clients()

    # ================================
    # Route messages
    # ================================

    async def _handle_client_message(self, client_message: ClientMessage) -> None:
        """Route client message to appropriate handler with client context.

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
            print(f"Unknown message type from {client_id}: {payload}")

    # ================================
    # Handle requests
    # ================================

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
            request_or_error = self.parser.parse_request(payload)

            if isinstance(request_or_error, Error):
                # Send parsing error back to client
                response = JSONRPCError.from_error(request_or_error, request_id)
                await self.transport.send_to_client(client_id, response.to_wire())
                return

            # Route to handler with typed request
            if handler := self._request_handlers.get(method):
                # Get or create client context
                context = self.client_manager.get_client(client_id)
                if not context:
                    context = self.client_manager.register_client(client_id)

                # Run as background task to avoid blocking message loop
                task = asyncio.create_task(
                    self._execute_request_handler(
                        handler, client_id, request_or_error, request_id
                    ),
                    name=f"handle_{method}_{client_id}_{request_id}",
                )

                # Store task in client context
                context.in_flight_requests[request_id] = task

                # Clean up when task completes
                task.add_done_callback(
                    lambda t: context.in_flight_requests.pop(request_id, None)
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

    # ================================
    # Handle notifications
    # ================================

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
            notification = self.parser.parse_notification(payload)

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

    # ================================
    # Handle responses
    # ================================

    async def _handle_response(self, client_id: str, payload: dict[str, Any]) -> None:
        """Handle response from client to our outbound request."""
        request_id = payload.get("id")
        if not request_id:
            print(f"Response from {client_id} missing request ID")
            return

        # Get context and work with it directly
        context = self.client_manager.get_client(client_id)
        if not context:
            print(f"No client context for {client_id}")
            return

        request_future_tuple = context.pending_requests.pop(request_id, None)
        if not request_future_tuple:
            print(f"No pending request {request_id} for client {client_id}")
            return

        original_request, future = request_future_tuple
        result_or_error = self.parser.parse_response(payload, original_request)
        future.set_result(result_or_error)

    # ================================
    # Cancel requests
    # ================================

    async def cancel_request(self, client_id: str, request_id: str | int) -> bool:
        """Cancel a specific request for a specific client."""
        context = self.client_manager.get_client(client_id)
        if not context:
            return False

        task = context.in_flight_requests.pop(request_id, None)
        if not task:
            return False

        task.cancel()
        return True

    async def cancel_client_requests(self, client_id: str) -> int:
        """Cancel all requests for a specific client. Returns count cancelled."""
        context = self.client_manager.get_client(client_id)
        if not context:
            return 0

        count = len(context.in_flight_requests)
        for task in context.in_flight_requests.values():
            task.cancel()
        context.in_flight_requests.clear()
        return count

    # ================================
    # Send requests
    # ================================

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
            Exception: If transport send fails
        """
        await self._ensure_ready_to_send()

        # Prepare the request
        request_id = str(uuid.uuid4())
        jsonrpc_request = JSONRPCRequest.from_request(request, request_id)
        future: asyncio.Future[Result | Error] = asyncio.Future()

        # Set up tracking
        self._ensure_client_registered(client_id)
        self.client_manager.track_pending_request(
            client_id, request_id, request, future
        )

        try:
            await self.transport.send_to_client(client_id, jsonrpc_request.to_wire())
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            await self._handle_request_timeout(client_id, request_id, timeout)
            raise
        finally:
            self.client_manager.remove_pending_request(client_id, request_id)

    async def _ensure_ready_to_send(self) -> None:
        """Ensure coordinator is running and transport is open."""
        if not self.running:
            await self.start()

        if not self.transport.is_open:
            raise ConnectionError("Cannot send request: transport is closed")

    def _ensure_client_registered(self, client_id: str) -> None:
        """Ensure client is registered with the client manager."""
        if not self.client_manager.get_client(client_id):
            self.client_manager.register_client(client_id)

    async def _handle_request_timeout(
        self, client_id: str, request_id: str, timeout: float
    ) -> None:
        """Clean up and notify client when request times out."""

        try:
            cancelled_notification = CancelledNotification(
                request_id=request_id,
                reason="Request timed out",
            )
            await self.send_notification_to_client(client_id, cancelled_notification)
        except Exception as e:
            print(f"Error sending cancellation to {client_id}: {e}")

    # ================================
    # Send notifications
    # ================================

    async def send_notification_to_client(
        self, client_id: str, notification: Notification
    ) -> None:
        """Send a notification to a specific client."""
        await self._ensure_ready_to_send()
        jsonrpc_notification = JSONRPCNotification.from_notification(notification)
        await self.transport.send_to_client(client_id, jsonrpc_notification.to_wire())

    # ================================
    # Register handlers
    # ================================

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

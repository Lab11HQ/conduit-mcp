"""Message processing mechanics for server sessions.

Handles the message loop, routing, and task management while keeping
the session focused on protocol logic rather than message processing.
"""

import asyncio
from typing import Any, Awaitable, Callable

from conduit.transport.server import ClientMessage, ServerTransport

# Handler signature - takes client_id and raw payload, returns nothing
# The handler is responsible for parsing and sending responses via transport
MessageHandler = Callable[[str, dict[str, Any]], Awaitable[None]]


class MessageProcessor:
    """Handles message processing mechanics for server sessions.

    Owns the message loop, manages background tasks, and routes messages
    to registered handlers with client context. Keeps the session focused
    on protocol logic rather than message processing mechanics.
    """

    def __init__(self, transport: ServerTransport):
        self.transport = transport
        self._handlers: dict[str, MessageHandler] = {}
        self._message_loop_task: asyncio.Task[None] | None = None
        self._in_flight_requests: dict[str, asyncio.Task[None]] = {}

    @property
    def running(self) -> bool:
        """True if the message loop is actively processing messages."""
        return (
            self._message_loop_task is not None and not self._message_loop_task.done()
        )

    def register_handler(self, method: str, handler: MessageHandler) -> None:
        """Register a handler for a specific method.

        Args:
            method: JSON-RPC method name (e.g., "tools/list")
            handler: Async function that takes (client_id, payload) and handles the
                message.
        """
        self._handlers[method] = handler

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
        for task in self._in_flight_requests.values():
            task.cancel()
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
        """Handle JSON-RPC request with client context.

        Looks up the handler for the method and runs it as a background task
        so it can't block other message processing.

        Args:
            client_id: ID of the client that sent the request
            payload: Raw JSON-RPC request payload
        """
        method = payload["method"]
        request_id = payload["id"]

        if handler := self._handlers.get(method):
            # Run as background task to avoid blocking message loop
            task_key = f"{client_id}_{request_id}"
            task = asyncio.create_task(
                handler(client_id, payload),
                name=f"handle_{method}_{client_id}_{request_id}",
            )
            self._in_flight_requests[task_key] = task
            task.add_done_callback(
                lambda t, key=task_key: self._in_flight_requests.pop(key, None)
            )
        else:
            # TODO: Send METHOD_NOT_FOUND error back to client
            print(f"Unknown method '{method}' from {client_id}")

    async def _handle_notification(
        self, client_id: str, payload: dict[str, Any]
    ) -> None:
        """Handle JSON-RPC notification with client context.

        Args:
            client_id: ID of the client that sent the notification
            payload: Raw JSON-RPC notification payload
        """
        method = payload["method"]

        if handler := self._handlers.get(method):
            # Run as background task (notifications don't need responses)
            asyncio.create_task(
                handler(client_id, payload), name=f"handle_{method}_{client_id}"
            )
        else:
            print(f"Unknown notification '{method}' from {client_id}")

    async def _handle_response(self, client_id: str, payload: dict[str, Any]) -> None:
        """Handle JSON-RPC response to a server->client request.

        This would be for cases where the server sent a request to the client
        (like sampling or elicitation) and the client is responding.

        Args:
            client_id: ID of the client that sent the response
            payload: Raw JSON-RPC response payload
        """
        # TODO: Implement response correlation for server->client requests
        print(f"Received response from {client_id}: {payload}")

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
        for request_task in self._in_flight_requests.values():
            request_task.cancel()
        self._in_flight_requests.clear()

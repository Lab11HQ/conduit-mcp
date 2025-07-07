import asyncio
from collections.abc import AsyncIterator
from typing import Any

from conduit.transport.http.server.connection_manager import ConnectionManager


class MessageSender:
    """Handles outbound messages from server to specific clients.

    Manages the server's side of HTTP communication:
    - Sends messages to specific clients via their SSE streams
    - Handles the GET endpoint that clients connect to
    - Manages per-client message queues and delivery
    """

    def __init__(self, connection_manager: ConnectionManager):
        self._connection_manager = connection_manager
        # Per-client message queues for SSE delivery
        self._client_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}

    async def send_to_client(self, client_id: str, message: dict[str, Any]) -> None:
        """Send a message to a specific client.

        Args:
            client_id: Session ID of the target client
            message: JSON-RPC message to send

        Raises:
            ValueError: If client_id is not an active session
        """
        # Validate client session
        if not self._connection_manager.validate_session(client_id):
            raise ValueError(f"Invalid or inactive client session: {client_id}")

        # TODO: Implement message delivery
        # - Get or create client queue
        # - Queue message for SSE delivery
        # - Handle queue overflow/backpressure

    async def get_client_stream(self, client_id: str) -> AsyncIterator[str]:
        """Get SSE stream for a specific client (GET endpoint handler).

        Args:
            client_id: Session ID of the requesting client

        Yields:
            str: SSE-formatted messages for the client

        Raises:
            ValueError: If client_id is not an active session
        """
        # Validate client session
        if not self._connection_manager.validate_session(client_id):
            raise ValueError(f"Invalid or inactive client session: {client_id}")

        # TODO: Implement SSE stream generation
        # - Create/get client message queue
        # - Format messages as SSE events
        # - Handle client disconnection
        # - Yield SSE-formatted strings

        # Placeholder for now
        yield "data: {}\n\n"

    def _ensure_client_queue(self, client_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Ensure a message queue exists for the client.

        Args:
            client_id: Session ID of the client

        Returns:
            asyncio.Queue for the client's messages
        """
        if client_id not in self._client_queues:
            self._client_queues[client_id] = asyncio.Queue()
        return self._client_queues[client_id]

    def cleanup_client(self, client_id: str) -> None:
        """Clean up resources for a disconnected client.

        Args:
            client_id: Session ID of the client to clean up
        """
        # TODO: Implement cleanup
        # - Remove client queue
        # - Cancel any pending tasks
        # - Clean up SSE streams

    async def close(self) -> None:
        """Close all client connections and clean up resources."""
        # TODO: Implement cleanup
        # - Close all client queues
        # - Cancel all SSE streams
        # - Clear tracking data

"""Server transport protocol - 1:many communication with clients."""

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol


@dataclass
class ClientMessage:
    """Message from a client with explicit connection context."""

    client_id: str
    payload: dict[str, Any]
    timestamp: float
    metadata: dict[str, Any] | None = None


class ServerTransport(Protocol):
    """Transport for server communicating with multiple clients.

    Handles the 1:many connection pattern where one server needs to
    communicate with multiple clients simultaneously.
    """

    async def send_to_client(self, client_id: str, message: dict[str, Any]) -> None:
        """Send message to specific client.

        Args:
            client_id: Target client session ID
            message: JSON-RPC message to send

        Raises:
            ValueError: If client_id is not an active session
        """
        ...

    async def broadcast(
        self, message: dict[str, Any], exclude: set[str] | None = None
    ) -> None:
        """Send message to all connected clients.

        Args:
            message: JSON-RPC message to broadcast
            exclude: Optional set of client IDs to exclude from broadcast
        """
        ...

    def client_messages(self) -> AsyncIterator[ClientMessage]:
        """Stream of messages from all clients with explicit client context.

        Yields:
            ClientMessage: Message with client ID and metadata
        """
        ...

    def active_clients(self) -> set[str]:
        """Get currently connected client IDs.

        Returns:
            Set of active client session IDs
        """
        ...

    async def disconnect_client(self, client_id: str) -> None:
        """Disconnect specific client.

        Args:
            client_id: Client session ID to disconnect
        """
        ...

    @property
    def is_open(self) -> bool:
        """True if server is open and accepting connections."""
        ...

    async def close(self) -> None:
        """Close server and disconnect all clients."""
        ...

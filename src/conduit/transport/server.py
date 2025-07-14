"""Server transport protocol - 1:many communication with clients."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator


@dataclass
class ClientMessage:
    """Message from a client with explicit connection context."""

    client_id: str
    payload: dict[str, Any]
    timestamp: float
    metadata: dict[str, Any] | None = None


class ServerTransport(ABC):
    """Transport for server communicating with multiple clients.

    Handles the 1:many connection pattern where one server needs to
    communicate with multiple clients simultaneously. Focuses purely
    on message passing - client lifecycle is managed by the session layer.
    """

    @abstractmethod
    async def send(self, client_id: str, message: dict[str, Any]) -> None:
        """Send message to specific client.

        Args:
            client_id: Target client session ID
            message: JSON-RPC message to send

        Raises:
            ValueError: If client_id is not an active session
        """
        ...

    @abstractmethod
    def client_messages(self) -> AsyncIterator[ClientMessage]:
        """Stream of messages from all clients with explicit client context.

        Yields:
            ClientMessage: Message with client ID and metadata
        """
        ...

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """True if server is open and accepting connections."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close server and disconnect all clients."""
        ...

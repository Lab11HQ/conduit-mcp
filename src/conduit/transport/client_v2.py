"""Multi-server client transport protocol - 1:many communication with servers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator


@dataclass
class ServerMessage:
    """Message from a server with explicit connection context."""

    server_id: str
    payload: dict[str, Any]
    timestamp: float
    metadata: dict[str, Any] | None = None


class ClientTransport(ABC):
    """Transport for client communicating with multiple servers.

    Handles the 1:many connection pattern where one client needs to
    communicate with multiple servers simultaneously. Focuses purely
    on message passing - server lifecycle is managed by the session layer.
    """

    @abstractmethod
    async def connect_server(self, server_id: str, connection_info: Any) -> None:
        """Connect to a specific server.

        Args:
            server_id: Unique identifier for this server connection
            connection_info: Transport-specific connection details

        Raises:
            ConnectionError: If connection cannot be established
            ValueError: If server_id is already connected
        """
        ...

    @abstractmethod
    async def send(self, server_id: str, message: dict[str, Any]) -> None:
        """Send message to specific server.

        Args:
            server_id: Target server connection ID
            message: JSON-RPC message to send

        Raises:
            ValueError: If server_id is not connected
            ConnectionError: If connection failed during send
        """
        ...

    @abstractmethod
    def server_messages(self) -> AsyncIterator[ServerMessage]:
        """Stream of messages from all servers with explicit server context.

        Yields:
            ServerMessage: Message with server ID and metadata
        """
        ...

    @abstractmethod
    async def disconnect_server(self, server_id: str) -> None:
        """Disconnect from specific server.

        Args:
            server_id: Server connection ID to disconnect

        Raises:
            ValueError: If server_id is not connected
        """
        ...

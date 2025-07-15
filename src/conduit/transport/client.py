from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class ClientTransport(ABC):
    """Transport for client communicating with a single server.

    Handles the 1:1 connection pattern where one client communicates
    with one server. Focuses purely on message passing - server lifecycle
    is managed by the session layer.
    """

    @abstractmethod
    async def open(self) -> None:
        """Open transport and establish connection to server.

        Raises:
            ConnectionError: If connection cannot be established
        """
        ...

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """True if client transport is open and connected to server."""
        ...

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        """Send message to the server.

        Args:
            message: JSON-RPC message to send

        Raises:
            ConnectionError: If transport is closed or connection failed
        """
        ...

    @abstractmethod
    def server_messages(self) -> AsyncIterator[dict[str, Any]]:
        """Stream of messages from the server.

        Yields:
            dict[str, Any]: Raw JSON-RPC message payload from server
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close connection to server."""
        ...

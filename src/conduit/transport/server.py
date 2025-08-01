"""Multi-client server transport protocol - 1:many communication with clients."""

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


@dataclass
class TransportContext:
    originating_request_id: str | int | None = None


class ServerTransport(ABC):
    """Transport for server communicating with multiple clients.

    Handles the 1:many connection pattern where one server needs to
    communicate with multiple clients simultaneously. Focuses purely
    on message passing - client lifecycle is managed by the session layer.
    """

    @abstractmethod
    async def send(
        self,
        client_id: str,
        message: dict[str, Any],
        transport_context: TransportContext | None = None,
    ) -> None:
        """Send message to specific client.

        Args:
            client_id: Target client connection ID
            message: JSON-RPC message to send
            transport_context: Context for the transport. For example, this helps route
                messages along specific streams.

        Raises:
            ValueError: If client_id is not connected
            ConnectionError: If connection failed during send
        """
        ...

    @abstractmethod
    def client_messages(self) -> AsyncIterator[ClientMessage]:
        """Stream of messages from all clients with explicit client context.

        Yields:
            ClientMessage: Message with client ID and metadata
        """
        ...

    @abstractmethod
    async def disconnect_client(self, client_id: str) -> None:
        """Disconnect specific client.

        Args:
            client_id: Client connection ID to disconnect
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the transport and clean up all resources.

        Should be called when the transport is no longer needed.
        Safe to call multiple times - subsequent calls are no-ops.
        """
        ...

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self


@dataclass
class TransportMessage:
    """Container for messages with transport-specific metadata.

    Separates the core MCP message payload from transport-specific
    information like headers, connection state, timing, etc.
    """

    payload: dict[str, Any] | list[dict[str, Any]]
    metadata: dict[str, Any]


class Transport(ABC):
    """Abstract transport for MCP message delivery.

    Handles the mechanics of sending and receiving messages
    without knowledge of protocol semantics or message correlation.

    Transports are bidirectional message streams:
    - Send messages via send()
    - Receive messages by iterating over messages()

    The transport handles connection lifecycle, framing, and error propagation.
    When connections fail, the message iterator raises appropriate exceptions.
    """

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """True if the transport is open and ready for message processing."""

    @abstractmethod
    async def send(self, payload: dict[str, Any]) -> None:
        """Send a message. Transport handles all metadata internally.

        Args:
            payload: The MCP message to send

        Raises:
            ConnectionError: If transport is closed or connection failed
        """

    @abstractmethod
    def messages(self) -> AsyncIterator[TransportMessage]:
        """Stream of incoming messages with transport-specific metadata.

        Yields messages as they arrive. Iterator ends when transport closes.

        Yields:
            TransportMessage: Each incoming message with metadata

        Raises:
            ConnectionError: When transport connection fails
            asyncio.CancelledError: When iteration is cancelled
        """

    @abstractmethod
    async def close(self) -> None:
        """Close the transport and stop message iteration."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()
        return None

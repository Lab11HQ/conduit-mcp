from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any, Self


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

    @abstractmethod
    async def send(self, payload: dict[str, Any]) -> None:
        """Send a message with any transport-specific metadata.

        Raises:
            ConnectionError: If transport is closed or connection failed
        """

    @abstractmethod
    def messages(self) -> AsyncIterator[dict[str, Any] | list[dict[str, Any]]]:
        """Stream of incoming messages with transport-specific metadata.

        Yields messages as they arrive. Iterator ends when transport closes.

        Yields:
            dict[str, Any] | list[dict[str, Any]]: Each incoming message

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

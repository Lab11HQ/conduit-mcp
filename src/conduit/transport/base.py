"""Transport layer abstraction for MCP protocol."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self


@dataclass
class TransportMessage:
    """A message with specific metadata for transport-specific features."""

    payload: dict[str, Any]
    metadata: dict[str, Any] | None = None


class Transport(ABC):
    """Abstract transport for MCP message delivery.

    Handles the mechanics of sending and receiving messages
    without knowledge of protocol semantics or message correlation.
    """

    @abstractmethod
    async def send(
        self, payload: dict[str, Any], metadata: dict[str, Any] | None = None
    ) -> None:
        """Send a message with any transport-specific metadata."""

    @abstractmethod
    async def receive(self) -> TransportMessage:
        """Receive the next message with any transport-specific metadata."""

    @abstractmethod
    async def close(self) -> None:
        """Close the transport."""

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

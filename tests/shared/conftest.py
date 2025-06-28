import asyncio
from collections.abc import AsyncIterator
from typing import Any

from conduit.protocol.base import Error, Result
from conduit.protocol.common import EmptyResult
from conduit.shared.session import BaseSession
from conduit.transport.base import Transport, TransportMessage


class MockTransport(Transport):
    """Mock transport for testing."""

    def __init__(self):
        self.sent_messages: list[dict[str, Any]] = []
        self._incoming_queue: asyncio.Queue[TransportMessage] = asyncio.Queue()
        self.closed = False
        self._should_raise_error = False

    def _receive_from_network(self, payload: dict[str, Any]) -> None:
        """Internal: simulate a message arriving from the network."""
        if self.closed:
            return
        transport_message = TransportMessage(
            payload=payload, metadata={"source": "mock", "timestamp": 0}
        )
        self._incoming_queue.put_nowait(transport_message)

    @property
    def is_open(self) -> bool:
        return not self.closed

    async def send(self, payload: dict[str, Any]) -> None:
        if self.closed:
            raise ConnectionError("Transport closed")
        self.sent_messages.append(payload)

    def simulate_error(self) -> None:
        """Simulate a connection error."""
        self._should_raise_error = True

    async def messages(self) -> AsyncIterator[TransportMessage]:
        """Stream of incoming messages - stays alive until closed."""
        while not self.closed:
            if self._should_raise_error:
                raise ConnectionError("Network down")
            try:
                transport_message = await asyncio.wait_for(
                    self._incoming_queue.get(), timeout=0.01
                )
                yield transport_message
            except asyncio.TimeoutError:
                continue  # Keep waiting for messages

    async def close(self) -> None:
        self.closed = True


class TestableBaseSession(BaseSession):
    """Concrete implementation of BaseSession for testing."""

    def __init__(self, transport: Transport):
        super().__init__(transport)
        self._is_initialized = True
        self.handled_requests: list[dict] = []

    @property
    def initialized(self) -> bool:
        return self._is_initialized

    def set_initialized(self, value: bool) -> None:
        """Helper for testing initialization state."""
        self._is_initialized = value

    def _handle_session_request(self, payload: dict[str, Any]) -> Result | Error:
        """Record handled requests and return a simple result."""
        self.handled_requests.append(payload)
        return EmptyResult()


class MockPeer:
    """Simulates the other end of the connection."""

    def __init__(self, transport: MockTransport):
        self.transport = transport

    def send_message(self, payload: dict[str, Any]) -> None:
        """Simulate peer sending a message."""
        self.transport._receive_from_network(payload)

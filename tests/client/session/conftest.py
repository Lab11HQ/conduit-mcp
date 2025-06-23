import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from conduit.client.session import ClientSession
from conduit.protocol.initialization import ClientCapabilities, Implementation
from conduit.transport.base import Transport, TransportMessage


class MockTransport(Transport):
    """Mock transport for testing."""

    def __init__(self):
        self.client_sent_messages: list[dict[str, Any]] = []
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

    async def send(self, payload: dict[str, Any]) -> None:
        if self.closed:
            raise ConnectionError("Transport closed")
        self.client_sent_messages.append(payload)

    def simulate_error(self) -> None:
        """Simulate a connection error. Raises ConnectionError in the message
        iterator. This is useful for testing the message loop's error handling.
        """
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


class MockServer:
    def __init__(self, transport: MockTransport):
        self.transport = transport

    def send_message(self, payload: dict[str, Any]) -> None:
        """Simulate server sending a message to the client."""
        self.transport._receive_from_network(payload)

    def send_batch_message(self, payload: list[dict[str, Any]]) -> None:
        """Simulate server sending a batch message to the client."""
        self.transport._receive_from_network(payload)


class BaseSessionTest:
    @pytest.fixture(autouse=True)
    def setup_fixtures(self):
        self.transport = MockTransport()
        self.session = ClientSession(
            transport=self.transport,
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(),
        )
        self.server = MockServer(transport=self.transport)

    @pytest.fixture(autouse=True)
    async def teardown_session(self):
        yield
        if hasattr(self, "session"):
            await self.session.stop()

    async def wait_for_sent_message(self, method: str) -> None:
        """Wait for a message to be sent - simple test sync helper."""
        for _ in range(100):  # Max 100ms wait
            if any(
                msg.get("method") == method
                for msg in self.transport.client_sent_messages
            ):
                return
            await asyncio.sleep(0.001)
        raise AssertionError(f"Message with method '{method}' never sent")

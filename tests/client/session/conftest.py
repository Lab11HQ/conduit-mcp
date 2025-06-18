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
        self.client_sent_messages: list[TransportMessage] = []
        self._incoming_queue: asyncio.Queue[TransportMessage] = asyncio.Queue()
        self.closed = False

    def _receive_from_network(
        self, payload: dict[str, Any], metadata: dict[str, Any] | None = None
    ) -> None:
        """Internal: simulate a message arriving from the network."""
        if self.closed:
            return
        message = TransportMessage(payload=payload, metadata=metadata)
        self._incoming_queue.put_nowait(message)

    async def send(
        self, payload: dict[str, Any], metadata: dict[str, Any] | None = None
    ) -> None:
        if self.closed:
            raise ConnectionError("Transport closed")
        self.client_sent_messages.append(
            TransportMessage(payload=payload, metadata=metadata)
        )

    async def messages(self) -> AsyncIterator[TransportMessage]:
        """Stream of incoming messages - stays alive until closed."""
        while not self.closed:
            try:
                message = await asyncio.wait_for(
                    self._incoming_queue.get(), timeout=0.01
                )
                yield message
            except asyncio.TimeoutError:
                continue  # Keep waiting for messages

    async def close(self) -> None:
        self.closed = True


class MockServer:
    def __init__(self, transport: MockTransport):
        self.transport = transport

    def send_message(
        self, payload: dict[str, Any], metadata: dict[str, Any] | None = None
    ) -> None:
        """Simulate server sending a message to the client."""
        self.transport._receive_from_network(payload, metadata)


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

    async def wait_for_sent_request(self, method: str) -> None:
        """Wait for a request to be sent - simple test sync helper."""
        for _ in range(100):  # Max 100ms wait
            if any(
                msg.payload.get("method") == method
                for msg in self.transport.client_sent_messages
            ):
                return
            await asyncio.sleep(0.001)
        raise AssertionError(f"Request {method} never sent")


# def numbered_ids(count):
#     """Generate numbered test IDs: id-1, id-2, etc."""
#     return iter(f"id-{i}" for i in range(1, count + 1))

# Usage:
# counter = numbered_ids(5)
# monkeypatch.setattr("conduit.client.session.uuid.uuid4", lambda: next(counter))

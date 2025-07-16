import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from conduit.server.client_manager import ClientManager
from conduit.server.coordinator_v2 import MessageCoordinator
from conduit.transport.server_v2 import ClientMessage, ServerTransport


class MockServerTransport(ServerTransport):
    """Simplified mock transport for testing MessageCoordinator."""

    def __init__(self):
        self.sent_messages: dict[str, list[dict[str, Any]]] = {}
        self.client_message_queue: asyncio.Queue[ClientMessage] = asyncio.Queue()
        self._should_raise_error = False

    async def send(self, client_id: str, message: dict[str, Any]) -> None:
        if self._should_raise_error:
            raise ConnectionError("Transport error")
        if client_id not in self.sent_messages:
            self.sent_messages[client_id] = []
        self.sent_messages[client_id].append(message)

    async def disconnect_client(self, client_id: str) -> None:
        """Disconnect specific client."""
        # For testing, just remove from sent_messages tracking
        if client_id in self.sent_messages:
            del self.sent_messages[client_id]

    def simulate_error(self) -> None:
        """Simulate a transport error."""
        self._should_raise_error = True

    def client_messages(self) -> AsyncIterator[ClientMessage]:
        return self._client_message_iterator()

    async def _client_message_iterator(self) -> AsyncIterator[ClientMessage]:
        while True:
            if self._should_raise_error:
                raise ConnectionError("Transport error")
            try:
                message = await asyncio.wait_for(
                    self.client_message_queue.get(), timeout=0.01
                )
                yield message
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    # Test helpers
    def add_client_message(self, client_id: str, payload: dict[str, Any]) -> None:
        """Add a message to the client message queue for testing."""
        message = ClientMessage(
            client_id=client_id,
            payload=payload,
            timestamp=asyncio.get_event_loop().time(),
        )
        self.client_message_queue.put_nowait(message)


@pytest.fixture
async def mock_transport():
    """Mock ServerTransport for testing."""
    transport = MockServerTransport()
    yield transport
    # No cleanup needed - transport has no lifecycle!


@pytest.fixture
def client_manager():
    """Fresh ClientManager for testing."""
    return ClientManager()


@pytest.fixture
async def coordinator(mock_transport, client_manager):
    """MessageCoordinator with mock dependencies and automatic cleanup."""
    coord = MessageCoordinator(mock_transport, client_manager)
    yield coord
    # Cleanup - ensure coordinator is stopped
    if coord.running:
        await coord.stop()


async def yield_to_event_loop(seconds: float = 0.01) -> None:
    """Let the event loop process pending tasks and callbacks.

    Args:
        seconds: Small delay to ensure async operations settle.
                Defaults to 10ms - enough for most async operations.
    """
    await asyncio.sleep(seconds)


@pytest.fixture
def yield_loop():
    """Helper to yield to event loop in tests."""
    return yield_to_event_loop

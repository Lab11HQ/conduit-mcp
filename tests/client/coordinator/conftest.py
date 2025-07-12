import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from conduit.client.coordinator import ClientMessageCoordinator
from conduit.client.server_manager import ServerManager
from conduit.transport.client import ClientTransport


class MockClientTransport(ClientTransport):
    """Mock transport for testing ClientMessageCoordinator."""

    def __init__(self):
        self.sent_messages: list[dict[str, Any]] = []
        self.server_message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._is_open = True

    @property
    def is_open(self) -> bool:
        return self._is_open

    async def send_to_server(self, message: dict[str, Any]) -> None:
        """Record sent messages for test assertions."""
        self.sent_messages.append(message)

    def server_messages(self) -> AsyncIterator[dict[str, Any]]:
        """Yield messages from the queue."""
        return self._server_message_iterator()

    async def _server_message_iterator(self) -> AsyncIterator[dict[str, Any]]:
        """Async iterator over server messages."""
        while self._is_open:
            try:
                message = await asyncio.wait_for(
                    self.server_message_queue.get(), timeout=0.01
                )
                yield message
            except asyncio.TimeoutError:
                if not self._is_open:
                    break
                continue
            except asyncio.CancelledError:
                break

    async def close(self) -> None:
        """Close the transport."""
        self._is_open = False
        # Clear the queue to help the iterator exit faster
        while not self.server_message_queue.empty():
            try:
                self.server_message_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    # Test helpers
    def add_server_message(self, message: dict[str, Any]) -> None:
        """Add a message to the queue (for tests to simulate server messages)."""
        self.server_message_queue.put_nowait(message)


@pytest.fixture
async def mock_transport():
    """Mock ClientTransport for testing with automatic cleanup."""
    transport = MockClientTransport()
    yield transport
    await transport.close()


@pytest.fixture
def server_manager():
    """Fresh ServerManager for testing."""
    return ServerManager()


@pytest.fixture
async def coordinator(mock_transport, server_manager):
    """ClientMessageCoordinator with mock dependencies and automatic cleanup."""
    coord = ClientMessageCoordinator(mock_transport, server_manager)
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

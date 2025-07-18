import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from conduit.client.coordinator import MessageCoordinator
from conduit.client.server_manager import ServerManager
from conduit.transport.client_v2 import ClientTransport, ServerMessage


class MockClientTransport(ClientTransport):
    """Mock transport for testing ClientMessageCoordinator with multi-server support."""

    def __init__(self):
        self.sent_messages: dict[str, list[dict[str, Any]]] = {}
        self.server_message_queue: asyncio.Queue[ServerMessage] = asyncio.Queue()
        self.registered_servers: dict[str, dict[str, Any]] = {}
        self._should_raise_error = False

    async def add_server(self, server_id: str, connection_info: dict[str, Any]) -> None:
        """Register how to reach a server (doesn't connect yet)."""
        if server_id in self.registered_servers:
            raise ValueError(f"Server {server_id} already registered")
        self.registered_servers[server_id] = connection_info

    async def send(self, server_id: str, message: dict[str, Any]) -> None:
        """Send message to specific server."""
        if self._should_raise_error:
            raise ConnectionError("Transport error")
        if server_id not in self.registered_servers:
            return  # Already disconnected - mission accomplished

        if server_id not in self.sent_messages:
            self.sent_messages[server_id] = []
        self.sent_messages[server_id].append(message)

    def server_messages(self) -> AsyncIterator[ServerMessage]:
        """Stream of messages from all servers with explicit server context."""
        return self._server_message_iterator()

    async def _server_message_iterator(self) -> AsyncIterator[ServerMessage]:
        """Async iterator over server messages."""
        while True:
            try:
                if self._should_raise_error:
                    raise ConnectionError("Transport error")
                message = await asyncio.wait_for(
                    self.server_message_queue.get(), timeout=0.01
                )
                yield message
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def disconnect_server(self, server_id: str) -> None:
        """Disconnect from specific server."""
        if server_id not in self.registered_servers:
            raise ValueError(f"Server {server_id} not registered")

        # Remove from tracking
        if server_id in self.sent_messages:
            del self.sent_messages[server_id]
        del self.registered_servers[server_id]

    def simulate_error(self) -> None:
        """Simulate a transport error."""
        self._should_raise_error = True

    # Test helpers
    def add_server_message(self, server_id: str, payload: dict[str, Any]) -> None:
        """Add a message to the queue (for tests to simulate server messages)."""
        message = ServerMessage(
            server_id=server_id,
            payload=payload,
            timestamp=asyncio.get_event_loop().time(),
        )
        self.server_message_queue.put_nowait(message)


@pytest.fixture
async def mock_transport():
    """Mock ClientTransport for testing with automatic cleanup."""
    transport = MockClientTransport()
    yield transport
    # No explicit cleanup needed - transport manages its own state


@pytest.fixture
def server_manager():
    """Fresh ServerManager for testing."""
    return ServerManager()


@pytest.fixture
async def coordinator(mock_transport, server_manager):
    """ClientMessageCoordinator with mock dependencies and automatic cleanup."""
    coord = MessageCoordinator(mock_transport, server_manager)
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

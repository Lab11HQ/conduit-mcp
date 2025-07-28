import asyncio
import time
from typing import Any, AsyncIterator

import pytest

from conduit.transport.client import ClientTransport, ServerMessage


class MockClientTransport(ClientTransport):
    """Mock transport for testing ClientSession with multi-server support."""

    def __init__(self):
        self.sent_messages: dict[str, list[dict[str, Any]]] = {}
        self.server_message_queue: asyncio.Queue[ServerMessage] = asyncio.Queue()
        self.registered_servers: dict[str, dict[str, Any]] = {}
        self._should_raise_error = False

    async def add_server(self, server_id: str, connection_info: dict[str, Any]) -> None:
        """Register how to reach a server (doesn't connect yet)."""
        self.registered_servers[server_id] = connection_info

    async def send(self, server_id: str, message: dict[str, Any]) -> None:
        """Send message to specific server."""
        if self._should_raise_error:
            raise ConnectionError("Transport error")
        if server_id not in self.registered_servers:
            raise ValueError(f"Server {server_id} not registered")

        if server_id not in self.sent_messages:
            self.sent_messages[server_id] = []
        self.sent_messages[server_id].append(message)

    def server_messages(self) -> AsyncIterator[ServerMessage]:
        """Stream of messages from all servers with explicit server context."""
        return self._server_message_iterator()

    async def _server_message_iterator(self) -> AsyncIterator[ServerMessage]:
        """Async iterator for server messages."""
        while True:
            if self._should_raise_error:
                raise ConnectionError("Transport error")
            try:
                message = await asyncio.wait_for(
                    self.server_message_queue.get(), timeout=0.01
                )
                yield message
            except asyncio.TimeoutError:
                continue

    async def disconnect_server(self, server_id: str) -> None:
        """Disconnect from specific server."""
        if server_id not in self.registered_servers:
            return  # Already disconnected - mission accomplished

        # Clean up server state
        self.registered_servers.pop(server_id, None)
        self.sent_messages.pop(server_id, None)

    # Helper methods for testing
    def add_server_message(self, server_id: str, payload: dict[str, Any]) -> None:
        """Simulate receiving a message from a server."""
        message = ServerMessage(
            server_id=server_id, payload=payload, timestamp=time.time(), metadata=None
        )
        self.server_message_queue.put_nowait(message)

    def simulate_error(self) -> None:
        """Simulate a transport error."""
        self._should_raise_error = True

    def get_sent_messages(self, server_id: str) -> list[dict[str, Any]]:
        """Get messages sent to a specific server."""
        return self.sent_messages.get(server_id, [])

    def clear_sent_messages(self) -> None:
        """Clear all sent message history."""
        self.sent_messages.clear()

    async def close(self) -> None:
        """Close the transport and clean up all resources."""
        pass


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

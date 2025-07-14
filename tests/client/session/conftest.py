import asyncio
from typing import Any

import pytest

from conduit.transport.client import ClientTransport


class MockClientTransport(ClientTransport):
    """Simple mock transport for client session testing."""

    def __init__(self):
        self.sent_messages: list[dict[str, Any]] = []
        self._incoming_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._is_open = True
        self._should_raise_error = False

    async def send(self, payload: dict[str, Any]) -> None:
        """Record sent messages."""
        if not self._is_open:
            raise ConnectionError("Transport closed")
        if self._should_raise_error:
            raise ConnectionError("Network error")
        self.sent_messages.append(payload)

    async def server_messages(self):
        """Stream of incoming messages from server."""
        while self._is_open:
            if self._should_raise_error:
                raise ConnectionError("Network error")
            try:
                message = await asyncio.wait_for(
                    self._incoming_queue.get(), timeout=0.01
                )
                yield message
            except asyncio.TimeoutError:
                continue

    def receive_message(self, payload: dict[str, Any]) -> None:
        """Simulate receiving a message from the server."""
        if self._is_open:
            self._incoming_queue.put_nowait(payload)

    def simulate_error(self) -> None:
        """Simulate a network error."""
        self._should_raise_error = True

    async def close(self) -> None:
        """Close the transport."""
        self._is_open = False

    @property
    def is_open(self) -> bool:
        return self._is_open


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

import asyncio
from typing import Any

import pytest

from conduit.client.session import ClientSession
from conduit.protocol.initialization import ClientCapabilities, Implementation
from conduit.transport.base import Transport, TransportMessage


class MockTransport(Transport):
    """Mock transport for testing."""

    def __init__(self):
        self.sent_messages: list[TransportMessage] = []
        self.incoming_queue: asyncio.Queue[TransportMessage] = asyncio.Queue()
        self.closed = False

    def queue_message(
        self, payload: dict[str, Any], metadata: dict[str, Any] | None = None
    ) -> None:
        """Queue a message to be received."""
        message = TransportMessage(payload=payload, metadata=metadata)
        self.incoming_queue.put_nowait(message)

    def queue_response(
        self, request_id: int, result: Any = None, error: dict | None = None
    ) -> None:
        """Helper: queue a JSON-RPC response."""
        payload = {"jsonrpc": "2.0", "id": request_id}
        if error:
            payload["error"] = error
        else:
            payload["result"] = result
        self.queue_message(payload)

    async def send(
        self, payload: dict[str, Any], metadata: dict[str, Any] | None = None
    ) -> None:
        if self.closed:
            raise ConnectionError("Transport closed")
        self.sent_messages.append(TransportMessage(payload=payload, metadata=metadata))

    async def receive(self) -> TransportMessage:
        if self.closed:
            raise ConnectionError("Transport closed")
        return await self.incoming_queue.get()

    async def close(self) -> None:
        self.closed = True


class BaseSessionTest:
    @pytest.fixture(autouse=True)
    def setup_fixtures(self):
        self.transport = MockTransport()
        self.session = ClientSession(
            self.transport,
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(),
        )

    async def wait_for_sent_request(self, method: str) -> None:
        """Wait for a request to be sent - simple test sync helper."""
        for _ in range(100):  # Max 100ms wait
            if any(
                msg.payload.get("method") == method
                for msg in self.transport.sent_messages
            ):
                return
            await asyncio.sleep(0.001)
        raise AssertionError(f"Request {method} never sent")

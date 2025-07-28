"""Tests for HttpServerTransport.client_messages method."""

import asyncio

import pytest

from conduit.transport.server import ClientMessage
from conduit.transport.streamable_http.server.transport import HttpServerTransport


class TestHttpServerTransportClientMessages:
    """Orchestration tests for HttpServerTransport.client_messages."""

    @pytest.fixture
    def transport(self):
        """Create transport instance."""
        return HttpServerTransport()

    async def test_client_messages_yields_queued_messages(self, transport):
        """Test that client_messages yields messages from the queue."""
        # Arrange
        test_message = ClientMessage(
            client_id="test-client",
            payload={"jsonrpc": "2.0", "method": "test"},
            timestamp=123.456,
        )

        # Put message in queue
        await transport._message_queue.put(test_message)

        # Act
        iterator = transport.client_messages()
        message = await iterator.__anext__()

        # Assert
        assert message == test_message
        assert message.client_id == "test-client"
        assert message.payload == {"jsonrpc": "2.0", "method": "test"}
        assert message.timestamp == 123.456

    async def test_client_messages_handles_multiple_messages(self, transport):
        """Test that client_messages handles multiple queued messages."""
        # Arrange
        messages = [
            ClientMessage("client-1", {"method": "test1"}, 1.0),
            ClientMessage("client-2", {"method": "test2"}, 2.0),
            ClientMessage("client-3", {"method": "test3"}, 3.0),
        ]

        # Queue all messages
        for msg in messages:
            await transport._message_queue.put(msg)

        # Act & Assert
        iterator = transport.client_messages()
        for expected_message in messages:
            received_message = await asyncio.wait_for(iterator.__anext__(), timeout=1.0)
            assert received_message == expected_message

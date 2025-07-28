"""Tests for HttpServerTransport.send method."""

from unittest.mock import AsyncMock, Mock

import pytest

from conduit.transport.server import TransportContext
from conduit.transport.streamable_http.server.transport import HttpServerTransport


class TestHttpServerTransportSend:
    """Test the send method of HttpServerTransport."""

    @pytest.fixture
    def transport(self):
        """Create transport instance with mocked dependencies."""
        # Arrange
        transport = HttpServerTransport()
        transport._session_manager = Mock()
        transport._stream_manager = AsyncMock()
        return transport

    async def test_send_successful_with_originating_request_id(self, transport):
        """Test successful message send with originating request ID."""
        # Arrange
        client_id = "test-client-123"
        message = {"jsonrpc": "2.0", "method": "test", "id": 1}
        transport_context = TransportContext(originating_request_id="req-456")

        transport._session_manager.get_session_id.return_value = "session-789"
        transport._stream_manager.send_to_existing_stream.return_value = True

        # Act
        await transport.send(client_id, message, transport_context)

        # Assert
        transport._session_manager.get_session_id.assert_called_once_with(client_id)
        transport._stream_manager.send_to_existing_stream.assert_awaited_once_with(
            client_id, message, "req-456"
        )

    async def test_send_successful_without_transport_context(self, transport):
        """Test successful message send without transport context."""
        # Arrange
        client_id = "test-client-123"
        message = {"jsonrpc": "2.0", "method": "test", "id": 1}

        transport._session_manager.get_session_id.return_value = "session-789"
        transport._stream_manager.send_to_existing_stream.return_value = True

        # Act
        await transport.send(client_id, message)

        # Assert
        transport._session_manager.get_session_id.assert_called_once_with(client_id)
        transport._stream_manager.send_to_existing_stream.assert_awaited_once_with(
            client_id, message, None
        )

    async def test_send_raises_value_error_for_nonexistent_client(self, transport):
        """Test that send raises ValueError when client doesn't exist."""
        # Arrange
        client_id = "nonexistent-client"
        message = {"jsonrpc": "2.0", "method": "test", "id": 1}

        transport._session_manager.get_session_id.return_value = None

        # Act & Assert
        with pytest.raises(ValueError):
            await transport.send(client_id, message)

        transport._session_manager.get_session_id.assert_called_once_with(client_id)
        transport._stream_manager.send_to_existing_stream.assert_not_awaited()

    async def test_send_raises_connection_error_when_no_streams_available(
        self, transport
    ):
        # Arrange
        client_id = "test-client-123"
        message = {"jsonrpc": "2.0", "method": "test", "id": 1}

        transport._session_manager.get_session_id.return_value = "session-789"
        transport._stream_manager.send_to_existing_stream.return_value = False

        # Act & Assert
        with pytest.raises(ConnectionError):
            await transport.send(client_id, message)

        transport._session_manager.get_session_id.assert_called_once_with(client_id)
        transport._stream_manager.send_to_existing_stream.assert_awaited_once_with(
            client_id, message, None
        )

    async def test_send_with_different_message_types(self, transport):
        # Arrange
        client_id = "test-client-123"
        transport._session_manager.get_session_id.return_value = "session-789"
        transport._stream_manager.send_to_existing_stream.return_value = True

        test_messages = [
            # Request
            {"jsonrpc": "2.0", "method": "test_request", "id": 1},
            # Response
            {"jsonrpc": "2.0", "result": {"data": "test"}, "id": 1},
            # Notification
            {"jsonrpc": "2.0", "method": "test_notification"},
            # Error response
            {"jsonrpc": "2.0", "error": {"code": -1, "message": "Test error"}, "id": 1},
        ]

        # Act & Assert
        for message in test_messages:
            await transport.send(client_id, message)

        # Verify all messages were sent
        assert transport._stream_manager.send_to_existing_stream.await_count == len(
            test_messages
        )

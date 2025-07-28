"""Tests for HttpServerTransport.close method."""

from unittest.mock import AsyncMock, Mock

import pytest

from conduit.transport.streamable_http.server.transport import HttpServerTransport


class TestHttpServerTransportClose:
    """Orchestration tests for HttpServerTransport.close."""

    @pytest.fixture
    def transport(self):
        """Create transport instance with mocked dependencies."""
        # Arrange
        transport = HttpServerTransport()
        transport._session_manager = Mock()
        transport._stream_manager = AsyncMock()
        # Mock the stop method to avoid actual server operations
        transport.stop = AsyncMock()
        return transport

    async def test_close_stops_server_and_cleans_up(self, transport):
        """Test that close properly stops server and cleans up resources."""
        # Arrange & Act
        await transport.close()

        # Assert
        transport.stop.assert_called_once()
        transport._session_manager.terminate_all_sessions.assert_called_once()
        transport._stream_manager.close_all_streams.assert_called_once()

    async def test_close_is_idempotent(self, transport):
        """Test that close can be called multiple times safely."""
        # Arrange & Act
        await transport.close()
        await transport.close()
        await transport.close()

        # Assert
        assert transport.stop.call_count == 3
        assert transport._session_manager.terminate_all_sessions.call_count == 3
        assert transport._stream_manager.close_all_streams.call_count == 3

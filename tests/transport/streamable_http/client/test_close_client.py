from unittest.mock import AsyncMock, MagicMock

from conduit.transport.streamable_http.client.transport import HttpClientTransport


class TestClose:
    async def test_close_stops_all_stream_listeners(self):
        # Arrange
        transport = HttpClientTransport()

        # Mock dependencies
        transport._stream_manager.stop_all_listeners = MagicMock()
        transport._http_client.aclose = AsyncMock()

        # Act
        await transport.close()

        # Assert
        transport._stream_manager.stop_all_listeners.assert_called_once()
        transport._http_client.aclose.assert_awaited_once()

    async def test_close_clears_all_state(self):
        # Arrange
        transport = HttpClientTransport()

        # Add some state to clear
        await transport.add_server("server1", {"endpoint": "https://example.com/mcp"})
        await transport.add_server("server2", {"endpoint": "https://api.test.com/mcp"})
        assert len(transport._servers) == 2
        transport._sessions["server1"] = "session-123"
        transport._sessions["server2"] = "session-456"

        # Act
        await transport.close()

        # Assert
        assert len(transport._servers) == 0
        assert len(transport._sessions) == 0

    async def test_close_closes_http_client(self):
        # Arrange
        transport = HttpClientTransport()

        # Mock HTTP client
        transport._http_client.aclose = AsyncMock()

        # Act
        await transport.close()

        # Assert
        transport._http_client.aclose.assert_awaited_once()

    async def test_close_is_safe_to_call_multiple_times(self):
        # Arrange
        # - Create transport and add initial state
        transport = HttpClientTransport()
        await transport.add_server(
            "test-server", {"endpoint": "https://example.com/mcp"}
        )
        transport._sessions["test-server"] = "session-123"

        # - Mock HTTP client
        transport._http_client.aclose = AsyncMock()

        # Act - Call close multiple times. Doesn't raise an error.
        await transport.close()
        await transport.close()  # Second call
        await transport.close()  # Third call

        # Assert
        assert len(transport._servers) == 0
        assert len(transport._sessions) == 0

    async def test_close_full_cleanup_orchestration(self):
        # Arrange
        transport = HttpClientTransport()

        # Set up full state
        await transport.add_server("server1", {"endpoint": "https://example.com/mcp"})
        await transport.add_server("server2", {"endpoint": "https://api.test.com/mcp"})
        transport._sessions["server1"] = "session-123"
        transport._sessions["server2"] = "session-456"

        # Mock dependencies
        transport._stream_manager.stop_all_listeners = MagicMock()
        transport._http_client.aclose = AsyncMock()

        # Act
        await transport.close()

        # Assert - All cleanup steps executed
        transport._stream_manager.stop_all_listeners.assert_called_once()
        assert len(transport._servers) == 0
        assert len(transport._sessions) == 0
        transport._http_client.aclose.assert_awaited_once()

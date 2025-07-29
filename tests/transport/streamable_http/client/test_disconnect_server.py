from unittest.mock import MagicMock, patch

import httpx

from conduit.transport.streamable_http.client.transport import HttpClientTransport


class TestDisconnectServer:
    async def test_disconnect_unregistered_server_is_noop(self):
        """Test disconnect is safe to call on unregistered servers."""
        # Arrange
        transport = HttpClientTransport()

        # Act - should not raise
        await transport.disconnect_server("unknown-server")

        # Assert - no streams to stop, no sessions to clean up
        assert "unknown-server" not in transport._servers
        assert "unknown-server" not in transport._sessions

    async def test_disconnect_server_without_session_stops_streams_only(self):
        """Test disconnect without session only stops streams and removes server."""
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        await transport.add_server(server_id, {"endpoint": "https://example.com/mcp"})

        # Mock stream manager
        transport._stream_manager.stop_server_listeners = MagicMock()

        # Act
        await transport.disconnect_server(server_id)

        # Assert
        transport._stream_manager.stop_server_listeners.assert_called_once_with(
            server_id
        )
        assert server_id not in transport._servers

    @patch("httpx.AsyncClient.delete")
    async def test_disconnect_server_with_session_attempts_graceful_termination(
        self, mock_delete
    ):
        """Test disconnect with session attempts DELETE and cleans up properly."""
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        session_id = "session-123"

        await transport.add_server(
            server_id,
            {
                "endpoint": "https://example.com/mcp",
                "headers": {"Authorization": "Bearer token"},
            },
        )
        transport._sessions[server_id] = session_id

        # Mock successful DELETE response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_delete.return_value = mock_response

        # Mock stream manager
        transport._stream_manager.stop_server_listeners = MagicMock()

        # Act
        await transport.disconnect_server(server_id)

        # Assert - Verify DELETE request was made
        mock_delete.assert_awaited_once()
        call_args = mock_delete.call_args
        assert call_args[0][0] == "https://example.com/mcp"  # endpoint

        headers = call_args[1]["headers"]
        assert headers["Mcp-Session-Id"] == session_id
        assert headers["MCP-Protocol-Version"]
        assert headers["Authorization"] == "Bearer token"  # Custom headers included

        # Assert - Verify cleanup
        transport._stream_manager.stop_server_listeners.assert_called_once_with(
            server_id
        )
        assert server_id not in transport._servers
        assert server_id not in transport._sessions

    @patch("httpx.AsyncClient.delete")
    async def test_disconnect_handles_405_method_not_allowed(self, mock_delete):
        """Test disconnect handles 405 response gracefully."""
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        await transport.add_server(server_id, {"endpoint": "https://example.com/mcp"})
        transport._sessions[server_id] = "session-123"

        # Mock 405 response
        mock_response = MagicMock()
        mock_response.status_code = 405
        mock_delete.return_value = mock_response

        # Act - should not raise
        await transport.disconnect_server(server_id)

        # Assert - session still gets cleaned up
        assert server_id not in transport._sessions
        assert server_id not in transport._servers

    @patch("httpx.AsyncClient.delete")
    async def test_disconnect_handles_delete_request_failure(self, mock_delete):
        """Test disconnect handles DELETE request failures gracefully."""
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        await transport.add_server(server_id, {"endpoint": "https://example.com/mcp"})
        transport._sessions[server_id] = "session-123"

        # Mock DELETE failure
        mock_delete.side_effect = httpx.ConnectError("Connection failed")

        # Act - should not raise
        await transport.disconnect_server(server_id)

        # Assert - cleanup still happens despite failure
        assert server_id not in transport._sessions
        assert server_id not in transport._servers

    @patch("httpx.AsyncClient.delete")
    async def test_disconnect_handles_unexpected_delete_response(self, mock_delete):
        """Test disconnect handles unexpected DELETE response codes."""
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        await transport.add_server(server_id, {"endpoint": "https://example.com/mcp"})
        transport._sessions[server_id] = "session-123"

        # Mock unexpected response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_delete.return_value = mock_response

        # Act - should not raise
        await transport.disconnect_server(server_id)

        # Assert - cleanup still happens
        assert server_id not in transport._sessions
        assert server_id not in transport._servers

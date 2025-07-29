from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from conduit.transport.streamable_http.client.transport import HttpClientTransport


class TestStartServerStream:
    def setup_method(self):
        self.transport = HttpClientTransport()

    @patch("httpx.AsyncClient.get")
    async def test_start_server_stream_happy_path(self, mock_get):
        """Test successful server stream start with SSE response."""
        # Arrange
        server_id = "test-server"
        await self.transport.add_server(
            server_id,
            {
                "endpoint": "https://example.com/mcp",
                "headers": {"Authorization": "Bearer token123"},
            },
        )

        # Mock successful SSE response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/event-stream"}
        mock_response.request.headers = {}
        mock_get.return_value = mock_response

        # Mock stream manager
        self.transport._stream_manager.start_stream_listener = AsyncMock()

        # Act
        await self.transport.start_server_stream(server_id)

        # Assert - Verify GET request was made correctly
        mock_get.assert_awaited_once()
        call_args = mock_get.call_args
        assert call_args[0][0] == "https://example.com/mcp"  # endpoint
        assert call_args[1]["timeout"] == 10.0

        # Verify headers were built correctly
        headers = call_args[1]["headers"]
        assert headers["Accept"] == "text/event-stream"
        assert headers["Authorization"] == "Bearer token123"  # Custom headers included
        assert "MCP-Protocol-Version" in headers

        # Verify stream manager was called
        self.transport._stream_manager.start_stream_listener.assert_awaited_once_with(
            server_id, mock_response, message_queue=self.transport._message_queue
        )

    @patch("httpx.AsyncClient.get")
    async def test_start_server_stream_get_request_failure(self, mock_get):
        """Test start_server_stream handles GET request failures."""
        # Arrange
        server_id = "test-server"
        await self.transport.add_server(
            server_id, {"endpoint": "https://example.com/mcp"}
        )

        # Mock GET request failure
        mock_get.side_effect = httpx.ConnectError("Connection failed")

        # Act & Assert
        with pytest.raises(
            ConnectionError, match="Failed to start server stream for 'test-server'"
        ):
            await self.transport.start_server_stream(server_id)

        # Verify GET was attempted
        mock_get.assert_awaited_once()

    @patch("httpx.AsyncClient.get")
    async def test_start_server_stream_unregistered_server_raises_value_error(
        self, mock_get
    ):
        """Test start_server_stream fails when server is not registered."""
        # Act & Assert
        with pytest.raises(
            ValueError, match="Server 'unknown-server' is not registered"
        ):
            await self.transport.start_server_stream("unknown-server")

        # Verify no GET request was made
        mock_get.assert_not_awaited()

    @patch("httpx.AsyncClient.get")
    async def test_start_server_stream_405_method_not_allowed(self, mock_get):
        """Test start_server_stream handles 405 Method Not Allowed."""
        # Arrange
        server_id = "test-server"
        await self.transport.add_server(
            server_id, {"endpoint": "https://example.com/mcp"}
        )

        # Mock 405 response
        mock_response = MagicMock()
        mock_response.status_code = 405
        mock_get.return_value = mock_response

        # Act & Assert
        with pytest.raises(ConnectionError):
            await self.transport.start_server_stream(server_id)

    @patch("httpx.AsyncClient.get")
    async def test_start_server_stream_404_session_expired(self, mock_get):
        """Test start_server_stream handles 404 with session expiry."""
        # Arrange
        server_id = "test-server"
        await self.transport.add_server(
            server_id, {"endpoint": "https://example.com/mcp"}
        )
        self.transport._sessions[server_id] = "session-123"

        # Mock 404 response with session ID in request headers
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.request.headers = {"Mcp-Session-Id": "session-123"}
        mock_get.return_value = mock_response

        # Act & Assert
        with pytest.raises(ConnectionError):
            await self.transport.start_server_stream(server_id)

        # Verify session was cleared
        assert server_id not in self.transport._sessions

    @patch("httpx.AsyncClient.get")
    async def test_start_server_stream_404_no_session(self, mock_get):
        """Test start_server_stream handles 404 without session."""
        # Arrange
        server_id = "test-server"
        await self.transport.add_server(
            server_id, {"endpoint": "https://example.com/mcp"}
        )

        # Mock 404 response without session ID
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.request.headers = {}
        mock_get.return_value = mock_response

        # Act & Assert
        with pytest.raises(ConnectionError):
            await self.transport.start_server_stream(server_id)

    @patch("httpx.AsyncClient.get")
    async def test_start_server_stream_other_http_error(self, mock_get):
        """Test start_server_stream handles other HTTP errors."""
        # Arrange
        server_id = "test-server"
        await self.transport.add_server(
            server_id, {"endpoint": "https://example.com/mcp"}
        )

        # Mock 500 response that raises when raise_for_status is called
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )
        mock_get.return_value = mock_response

        # Act & Assert
        with pytest.raises(ConnectionError):
            await self.transport.start_server_stream(server_id)

    @patch("httpx.AsyncClient.get")
    async def test_start_server_stream_invalid_content_type(self, mock_get):
        """Test start_server_stream handles non-SSE content type."""
        # Arrange
        server_id = "test-server"
        await self.transport.add_server(
            server_id, {"endpoint": "https://example.com/mcp"}
        )

        # Mock 200 response with wrong content type
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_get.return_value = mock_response

        # Act & Assert
        with pytest.raises(ConnectionError):
            await self.transport.start_server_stream(server_id)

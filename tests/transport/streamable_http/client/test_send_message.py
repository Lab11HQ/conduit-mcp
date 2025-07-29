from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from conduit.transport.streamable_http.client.transport import HttpClientTransport


class TestSend:
    async def test_unregistered_server_raises_value_error(self):
        """Test send fails when server is not registered."""
        # Arrange
        transport = HttpClientTransport()
        message = {"method": "ping", "id": 1}

        # Act & Assert
        with pytest.raises(ValueError):
            await transport.send("unknown-server", message)

    @patch("httpx.AsyncClient.post")
    async def test_json_response_success(self, mock_post):
        """Test successful send with JSON response."""
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        await transport.add_server(server_id, {"endpoint": "https://example.com/mcp"})

        message = {"method": "ping", "id": 1}

        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"result": "pong", "id": 1}
        mock_response.request.headers = {}
        mock_post.return_value = mock_response

        # Act
        await transport.send(server_id, message)

        # Assert
        mock_post.assert_awaited_once()
        call_args = mock_post.call_args
        assert call_args[1]["json"] == message
        assert call_args[0][0] == "https://example.com/mcp"

        # Verify headers were set correctly
        headers = call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json, text/event-stream"
        assert "MCP-Protocol-Version" in headers

    @patch("httpx.AsyncClient.post")
    async def test_full_happy_path_with_message_retrieval(self, mock_post):
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        custom_headers = {"Authorization": "Bearer secret-token"}

        await transport.add_server(
            server_id,
            {"endpoint": "https://api.example.com/mcp", "headers": custom_headers},
        )

        request_message = {"jsonrpc": "2.0", "method": "tools/list", "id": "req-123"}

        response_payload = {
            "jsonrpc": "2.0",
            "result": {
                "tools": [
                    {"name": "calculator", "description": "Basic math operations"}
                ]
            },
            "id": "req-123",
        }

        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json; charset=utf-8"}
        mock_response.json.return_value = response_payload
        mock_response.request.headers = {}
        mock_post.return_value = mock_response

        # Act - Send the message
        await transport.send(server_id, request_message)

        # Assert - Verify HTTP request was made correctly
        mock_post.assert_awaited_once()
        call_args = mock_post.call_args

        # Check endpoint and payload
        assert call_args[0][0] == "https://api.example.com/mcp"
        assert call_args[1]["json"] == request_message
        assert call_args[1]["timeout"] == 30.0

        # Check headers include our custom headers
        sent_headers = call_args[1]["headers"]
        assert sent_headers["Content-Type"] == "application/json"
        assert sent_headers["Accept"] == "application/json, text/event-stream"
        assert sent_headers["Authorization"] == "Bearer secret-token"
        assert "MCP-Protocol-Version" in sent_headers

        # Act - Retrieve message from queue
        message_iterator = transport.server_messages()
        server_message = await message_iterator.__anext__()

        # Assert - Verify the response was queued correctly
        assert server_message.server_id == server_id
        assert server_message.payload == response_payload
        assert isinstance(server_message.timestamp, float)

    @patch("httpx.AsyncClient.post")
    async def test_http_request_error_raises_connection_error(self, mock_post):
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        await transport.add_server(server_id, {"endpoint": "https://example.com/mcp"})

        message = {"method": "ping", "id": 1}

        # Mock HTTP request failure
        mock_post.side_effect = httpx.ConnectError("Connection failed")

        # Act & Assert
        with pytest.raises(ConnectionError):
            await transport.send(server_id, message)

    @patch("httpx.AsyncClient.post")
    async def test_session_expired_404_raises_connection_error(self, mock_post):
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        await transport.add_server(server_id, {"endpoint": "https://example.com/mcp"})

        # Simulate having a session
        transport._sessions[server_id] = "session-123"

        message = {"method": "ping", "id": 1}

        # Mock 404 response with session ID in request headers
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.request.headers = {"Mcp-Session-Id": "session-123"}
        mock_post.return_value = mock_response

        # Act & Assert
        with pytest.raises(ConnectionError):
            await transport.send(server_id, message)

        # Verify session was cleared
        assert server_id not in transport._sessions

    @patch("httpx.AsyncClient.post")
    async def test_regular_404_raises_connection_error(self, mock_post):
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        await transport.add_server(server_id, {"endpoint": "https://example.com/mcp"})

        message = {"method": "ping", "id": 1}

        # Mock regular 404 response (no session ID in request)
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.request.headers = {}  # No session ID
        mock_response.text = "Endpoint not found"
        mock_post.return_value = mock_response

        # Act & Assert
        with pytest.raises(ConnectionError):
            await transport.send(server_id, message)

    @patch("httpx.AsyncClient.post")
    async def test_other_http_error_raises_for_status(self, mock_post):
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        await transport.add_server(server_id, {"endpoint": "https://example.com/mcp"})

        message = {"method": "ping", "id": 1}

        # Mock 500 response that raises when raise_for_status is called
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )
        mock_post.return_value = mock_response

        # Act & Assert
        with pytest.raises(httpx.HTTPStatusError):
            await transport.send(server_id, message)

    @patch("httpx.AsyncClient.post")
    async def test_202_accepted_success(self, mock_post):
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        await transport.add_server(server_id, {"endpoint": "https://example.com/mcp"})

        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {},
        }

        # Mock 202 response
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_post.return_value = mock_response

        # Act
        await transport.send(server_id, notification)

        # Assert - Should complete without error, no message queued
        mock_post.assert_awaited_once()

    @patch("httpx.AsyncClient.post")
    async def test_sse_stream_response_delegates_to_stream_manager(self, mock_post):
        """Test send delegates SSE streams to the stream manager."""
        # Arrange
        transport = HttpClientTransport()
        server_id = "test-server"
        await transport.add_server(server_id, {"endpoint": "https://example.com/mcp"})

        message = {"jsonrpc": "2.0", "method": "tools/call", "id": 1}

        # Mock SSE response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/event-stream"}
        mock_response.request.headers = {}
        mock_post.return_value = mock_response

        # Mock the stream manager directly on the transport instance
        transport._stream_manager.start_stream_listener = AsyncMock()

        # Act
        await transport.send(server_id, message)

        # Assert
        mock_post.assert_awaited_once()
        transport._stream_manager.start_stream_listener.assert_awaited_once_with(
            server_id, mock_response, message_queue=transport._message_queue
        )

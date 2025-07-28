"""Tests for HttpServerTransport GET request handler."""

from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request
from starlette.responses import StreamingResponse

from conduit.protocol.base import PROTOCOL_VERSION
from conduit.transport.streamable_http.server.transport import HttpServerTransport


class TestGetHandler:
    @pytest.fixture
    def transport(self):
        # Arrange
        transport = HttpServerTransport()
        # Keep real session manager, just mock stream manager
        transport._stream_manager = AsyncMock()
        return transport

    @pytest.fixture
    def mock_stream(self):
        """Create a mock stream object."""
        stream = Mock()
        stream.stream_id = "test-stream-123"
        stream.event_generator = Mock(return_value=iter(["data: test\n\n"]))
        return stream

    async def test_get_request_success_creates_server_stream(
        self, transport, mock_stream
    ):
        # Arrange
        client_id, session_id = transport._session_manager.create_session()

        # Mock successful stream creation
        transport._stream_manager.create_server_stream.return_value = mock_stream

        # Create request with proper headers
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            "Mcp-Session-Id": session_id,
        }
        request = Mock(spec=Request)
        request.headers = headers

        # Act
        response = await transport._handle_get_request(request)

        # Assert
        # Verify response type and media type
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"

        # Verify key headers
        assert response.headers["Content-Type"] == "text/event-stream"
        assert response.headers["Mcp-Session-Id"] == session_id
        assert response.headers["MCP-Protocol-Version"] == PROTOCOL_VERSION

        # Verify stream creation
        transport._stream_manager.create_server_stream.assert_awaited_once_with(
            client_id
        )

    async def test_get_request_invalid_accept_header_returns_400(self, transport):
        # Arrange
        client_id, session_id = transport._session_manager.create_session()

        # Create request with invalid Accept header (missing text/event-stream)
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "application/json",  # Missing text/event-stream
            "Origin": "https://example.com",
            "Mcp-Session-Id": session_id,
        }
        request = Mock(spec=Request)
        request.headers = headers

        # Act
        response = await transport._handle_get_request(request)

        # Assert
        assert response.status_code == 400
        assert "Invalid Accept header" in response.body.decode()

        # Verify stream creation was never attempted
        transport._stream_manager.create_server_stream.assert_not_awaited()

    async def test_get_request_missing_session_id_returns_400(self, transport):
        # Arrange
        # Create request with valid headers but no session ID
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            # Note: No Mcp-Session-Id header
        }
        request = Mock(spec=Request)
        request.headers = headers

        # Act
        response = await transport._handle_get_request(request)

        # Assert
        assert response.status_code == 400
        assert "Missing session ID" in response.body.decode()

        # Verify stream creation was never attempted
        transport._stream_manager.create_server_stream.assert_not_awaited()

    async def test_get_request_invalid_session_id_returns_404(self, transport):
        # Arrange
        # Create request with valid headers but non-existent session ID
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            "Mcp-Session-Id": "non-existent-session-123",
        }
        request = Mock(spec=Request)
        request.headers = headers

        # Act
        response = await transport._handle_get_request(request)

        # Assert
        assert response.status_code == 404
        assert "Invalid or expired session" in response.body.decode()

        # Verify stream creation was never attempted
        transport._stream_manager.create_server_stream.assert_not_awaited()

    async def test_get_request_stream_creation_failure_returns_500(self, transport):
        # Arrange
        client_id, session_id = transport._session_manager.create_session()

        # Mock stream creation to raise an exception
        transport._stream_manager.create_server_stream.side_effect = Exception(
            "Stream creation failed"
        )

        # Create request with valid headers and session
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            "Mcp-Session-Id": session_id,
        }
        request = Mock(spec=Request)
        request.headers = headers

        # Act
        response = await transport._handle_get_request(request)

        # Assert
        assert response.status_code == 500
        assert "Internal server error" in response.body.decode()

        # Verify stream creation was attempted
        transport._stream_manager.create_server_stream.assert_awaited_once_with(
            client_id
        )

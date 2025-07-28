"""Tests for HttpServerTransport POST request handler."""

import json
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from conduit.protocol.base import PROTOCOL_VERSION
from conduit.transport.streamable_http.server.transport import HttpServerTransport


class TestPostRequestProcessing:
    """Test POST request processing: headers, JSON parsing, routing."""

    @pytest.fixture
    def transport(self):
        """Create transport instance with mocked stream manager."""
        # Arrange
        transport = HttpServerTransport()
        transport._stream_manager = AsyncMock()
        return transport

    @pytest.fixture
    def mock_stream(self):
        """Create a mock stream object."""
        stream = Mock()
        stream.stream_id = "test-stream-123"

        async def mock_event_generator():
            yield "data: test\n\n"

        stream.event_generator = Mock(return_value=mock_event_generator())
        return stream

    async def test_mcp_request_creates_stream(self, transport, mock_stream):
        """Test POST with MCP request creates request stream."""
        # Arrange
        client_id, session_id = transport._session_manager.create_session()

        # Mock successful stream creation
        transport._stream_manager.create_request_stream = AsyncMock(
            return_value=mock_stream
        )

        # Create MCP request message (has method + id)
        message_data = {"jsonrpc": "2.0", "method": "tools/list", "id": "req-123"}

        # Create request with proper headers and body
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            "Mcp-Session-Id": session_id,
        }
        request = Mock(spec=Request)
        request.headers = headers
        request.json = AsyncMock(return_value=message_data)

        # Act
        response = await transport._handle_post_request(request)

        # Assert
        # Verify it's a streaming response
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"

        # Verify key headers
        assert response.headers["Mcp-Session-Id"] == session_id
        assert response.headers["MCP-Protocol-Version"] == PROTOCOL_VERSION

        # Verify request stream creation
        transport._stream_manager.create_request_stream.assert_awaited_once_with(
            client_id, "req-123"
        )

        # Verify message was queued
        assert not transport._message_queue.empty()
        queued_message = await transport._message_queue.get()
        assert queued_message.client_id == client_id
        assert queued_message.payload == message_data

    async def test_mcp_notification_returns_202(self, transport):
        """Test POST with notification returns 202 response."""
        # Arrange
        client_id, session_id = transport._session_manager.create_session()

        # Create notification message (has method but no id)
        message_data = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
        }

        # Create request with proper headers and body
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            "Mcp-Session-Id": session_id,
        }
        request = Mock(spec=Request)
        request.headers = headers
        request.json = AsyncMock(return_value=message_data)

        # Act
        response = await transport._handle_post_request(request)

        # Assert
        # Verify it's a 202 response (not 200, streaming)
        assert isinstance(response, Response)
        assert response.status_code == 202

        # Verify key headers
        assert response.headers["Mcp-Session-Id"] == session_id
        assert response.headers["MCP-Protocol-Version"] == PROTOCOL_VERSION

        # Verify no stream creation attempted
        transport._stream_manager.create_request_stream.assert_not_awaited()

        # Verify message was still queued
        assert not transport._message_queue.empty()
        queued_message = await transport._message_queue.get()
        assert queued_message.client_id == client_id
        assert queued_message.payload == message_data

    async def test_missing_protocol_version_returns_400(self, transport):
        # Arrange
        client_id, session_id = transport._session_manager.create_session()

        message_data = {"jsonrpc": "2.0", "method": "tools/list", "id": "req-123"}

        # Create request with missing MCP-Protocol-Version header
        headers = {
            # Missing: "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            "Mcp-Session-Id": session_id,
        }
        request = Mock(spec=Request)
        request.headers = headers
        request.json = AsyncMock(return_value=message_data)

        # Act
        response = await transport._handle_post_request(request)

        # Assert
        assert response.status_code == 400
        assert "Missing MCP-Protocol-Version header" in response.body.decode()

        # Verify early exit - no JSON parsing or stream creation
        request.json.assert_not_awaited()
        transport._stream_manager.create_request_stream.assert_not_awaited()

        # Verify message queue is empty (never got that far)
        assert transport._message_queue.empty()

    async def test_malformed_json_returns_400(self, transport):
        """Test POST with malformed JSON returns 400."""
        # Arrange
        client_id, session_id = transport._session_manager.create_session()

        # Create request with valid headers but malformed JSON body
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            "Mcp-Session-Id": session_id,
        }
        request = Mock(spec=Request)
        request.headers = headers
        # Mock request.json() to raise JSONDecodeError
        request.json = AsyncMock(
            side_effect=json.JSONDecodeError("Expecting value", "doc", 0)
        )

        # Act
        response = await transport._handle_post_request(request)

        # Assert
        assert response.status_code == 400
        assert "Invalid JSON" in response.body.decode()

        # Verify no stream creation attempted
        transport._stream_manager.create_request_stream.assert_not_awaited()

        # Verify message queue is empty (never got that far)
        assert transport._message_queue.empty()

    async def test_non_dict_json_returns_400(self, transport):
        """Test POST with non-dict JSON returns 400."""
        # Arrange
        client_id, session_id = transport._session_manager.create_session()

        # Create request with valid headers but non-dict JSON body
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            "Mcp-Session-Id": session_id,
        }
        request = Mock(spec=Request)
        request.headers = headers
        # Valid JSON but not a dict
        request.json = AsyncMock(return_value=["valid", "json", "array"])

        # Act
        response = await transport._handle_post_request(request)

        # Assert
        assert response.status_code == 400
        assert "Invalid JSON" in response.body.decode()

        # Verify no stream creation attempted
        transport._stream_manager.create_request_stream.assert_not_awaited()

        # Verify message queue is empty (never got that far)
        assert transport._message_queue.empty()

    async def test_invalid_jsonrpc_message_returns_400(self, transport):
        """Test POST with invalid JSON-RPC message returns 400."""
        # Arrange
        client_id, session_id = transport._session_manager.create_session()

        # Create message that's valid JSON dict but invalid JSON-RPC
        message_data = {
            "not_jsonrpc": "2.0",
            "invalid": "structure",
            # Missing required jsonrpc field, method/result, etc.
        }

        # Create request with valid headers and invalid JSON-RPC body
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            "Mcp-Session-Id": session_id,
        }
        request = Mock(spec=Request)
        request.headers = headers
        request.json = AsyncMock(return_value=message_data)

        # Act
        response = await transport._handle_post_request(request)

        # Assert
        assert response.status_code == 400
        assert "Invalid JSON-RPC message" in response.body.decode()

        # Verify no stream creation attempted
        transport._stream_manager.create_request_stream.assert_not_awaited()

        # Verify message queue is empty (never got that far)
        assert transport._message_queue.empty()


class TestSessionValidation:
    """Test session validation logic in POST handler."""

    @pytest.fixture
    def transport(self):
        """Create transport instance with mocked stream manager."""
        # Arrange
        transport = HttpServerTransport()
        transport._stream_manager = AsyncMock()
        return transport

    async def test_initialize_request_without_session_succeeds(self, transport):
        """Test POST initialize request without session ID succeeds."""
        # Arrange
        # Create dummy initialize request (no session ID should be provided)
        message_data = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": "init-123",
            "params": {"protocolVersion": PROTOCOL_VERSION},
        }

        # Create request with valid headers but NO session ID
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            # Note: No Mcp-Session-Id header for initialize
        }
        request = Mock(spec=Request)
        request.headers = headers
        request.json = AsyncMock(return_value=message_data)

        # Mock stream creation for the successful case
        mock_stream = Mock()

        async def mock_event_generator():
            yield "data: test\n\n"

        mock_stream.event_generator = Mock(return_value=mock_event_generator())
        transport._stream_manager.create_request_stream = AsyncMock(
            return_value=mock_stream
        )

        # Act
        response = await transport._handle_post_request(request)

        # Assert
        # Should succeed and create a stream (initialize is an MCP request)
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"

        # Should have created a new session
        assert "Mcp-Session-Id" in response.headers
        new_session_id = response.headers["Mcp-Session-Id"]

        # Verify stream creation with new client
        transport._stream_manager.create_request_stream.assert_awaited_once()

        # Verify message was queued with new client_id
        assert not transport._message_queue.empty()
        queued_message = await transport._message_queue.get()
        assert queued_message.payload == message_data

    async def test_initialize_request_with_session_returns_400(self, transport):
        """Test POST initialize request with session ID returns 400."""
        # Arrange
        client_id, session_id = transport._session_manager.create_session()

        # Create dummy initialize request (should NOT have session ID)
        message_data = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": "init-123",
            "params": {"protocolVersion": PROTOCOL_VERSION},
        }

        # Create request with session ID (this is the error)
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            "Mcp-Session-Id": session_id,  # This should NOT be here for initialize
        }
        request = Mock(spec=Request)
        request.headers = headers
        request.json = AsyncMock(return_value=message_data)

        # Act
        response = await transport._handle_post_request(request)

        # Assert
        assert response.status_code == 400
        assert (
            "Initialize request must not include session ID" in response.body.decode()
        )

        # Verify no stream creation attempted
        transport._stream_manager.create_request_stream.assert_not_awaited()

        # Verify message queue is empty (never got that far)
        assert transport._message_queue.empty()

    async def test_non_initialize_request_missing_session_returns_400(self, transport):
        # Arrange
        # Create non-initialize request (requires session ID)
        message_data = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": "req-123",
        }

        # Create request without session ID (this is the error)
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            # Note: Missing Mcp-Session-Id header
        }
        request = Mock(spec=Request)
        request.headers = headers
        request.json = AsyncMock(return_value=message_data)

        # Act
        response = await transport._handle_post_request(request)

        # Assert
        assert response.status_code == 400
        assert "Missing Mcp-Session-Id header" in response.body.decode()

        # Verify no stream creation attempted
        transport._stream_manager.create_request_stream.assert_not_awaited()

        # Verify message queue is empty (never got that far)
        assert transport._message_queue.empty()

    async def test_non_initialize_request_invalid_session_returns_404(self, transport):
        # Arrange
        # Create non-initialize request
        message_data = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": "req-123",
        }

        # Create request with non-existent session ID
        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            "Mcp-Session-Id": "non-existent-session-456",
        }
        request = Mock(spec=Request)
        request.headers = headers
        request.json = AsyncMock(return_value=message_data)

        # Act
        response = await transport._handle_post_request(request)

        # Assert
        assert response.status_code == 404
        assert "Invalid or expired Mcp-Session-Id" in response.body.decode()

        # Verify no stream creation attempted
        transport._stream_manager.create_request_stream.assert_not_awaited()

        # Verify message queue is empty (never got that far)
        assert transport._message_queue.empty()

    async def test_initialize_creates_new_client_and_session(self, transport):
        """Test POST initialize request creates new client and session."""
        # Arrange
        message_data = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": "init-123",
            "params": {"protocolVersion": PROTOCOL_VERSION},
        }

        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            # No session ID for initialize
        }
        request = Mock(spec=Request)
        request.headers = headers
        request.json = AsyncMock(return_value=message_data)

        # Mock stream creation
        mock_stream = Mock()

        async def mock_event_generator():
            yield "data: test\n\n"

        mock_stream.event_generator = Mock(return_value=mock_event_generator())
        transport._stream_manager.create_request_stream = AsyncMock(
            return_value=mock_stream
        )

        # Act
        response = await transport._handle_post_request(request)

        # Assert
        # Verify new session was created and returned
        assert "Mcp-Session-Id" in response.headers
        new_session_id = response.headers["Mcp-Session-Id"]

        # Verify the session actually exists in the session manager
        assert transport._session_manager.session_exists(new_session_id)

        # Verify we can get the client ID for this session
        client_id = transport._session_manager.get_client_id(new_session_id)
        assert client_id is not None

    async def test_post_request_stream_creation_failure_returns_500(self, transport):
        """Test POST MCP request returns 500 when stream creation fails."""
        # Arrange
        client_id, session_id = transport._session_manager.create_session()

        # Mock stream creation to raise an exception
        transport._stream_manager.create_request_stream.side_effect = Exception(
            "Stream creation failed"
        )

        message_data = {"jsonrpc": "2.0", "method": "tools/list", "id": "req-123"}

        headers = {
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Accept": "text/event-stream, application/json",
            "Origin": "https://example.com",
            "Mcp-Session-Id": session_id,
        }
        request = Mock(spec=Request)
        request.headers = headers
        request.json = AsyncMock(return_value=message_data)

        # Act
        response = await transport._handle_post_request(request)

        # Assert
        assert response.status_code == 500
        assert "Internal server error" in response.body.decode()

        # Verify stream creation was attempted
        transport._stream_manager.create_request_stream.assert_awaited_once_with(
            client_id, "req-123"
        )

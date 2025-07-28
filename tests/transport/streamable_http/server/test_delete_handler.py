"""Tests for HttpServerTransport DELETE request handler."""

from unittest.mock import Mock

import pytest
from starlette.requests import Request

from conduit.transport.streamable_http.server.transport import HttpServerTransport


class TestDeleteRequestProcessing:
    """Test DELETE request processing: headers, session validation."""

    @pytest.fixture
    def transport(self):
        """Create transport instance."""
        # Arrange
        return HttpServerTransport()

    async def test_valid_session_returns_200(self, transport):
        # Arrange
        client_id, session_id = transport._session_manager.create_session()

        # Create request with valid session ID
        request = Mock(spec=Request)
        request.headers = {"Mcp-Session-Id": session_id}

        # Act
        response = await transport._handle_delete_request(request)

        # Assert
        assert response.status_code == 200
        assert response.body == b""  # No body content

        # Verify session was actually terminated
        assert not transport._session_manager.session_exists(session_id)

    async def test_missing_session_id_returns_400(self, transport):
        # Arrange
        # Create request without session ID
        request = Mock(spec=Request)
        request.headers = {}

        # Act
        response = await transport._handle_delete_request(request)

        # Assert
        assert response.status_code == 400
        assert response.body.decode() == "Missing session ID"

    async def test_invalid_session_id_returns_404(self, transport):
        # Arrange
        # Create request with non-existent session ID
        request = Mock(spec=Request)
        request.headers = {"Mcp-Session-Id": "non-existent-session-123"}

        # Act
        response = await transport._handle_delete_request(request)

        # Assert
        assert response.status_code == 404
        assert response.body.decode() == "Session not found"

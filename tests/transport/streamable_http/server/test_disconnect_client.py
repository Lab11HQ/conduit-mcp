"""Tests for HttpServerTransport.disconnect_client method."""

from unittest.mock import Mock

import pytest

from conduit.transport.streamable_http.server.transport import HttpServerTransport


class TestHttpServerTransportDisconnectClient:
    """Orchestration tests for HttpServerTransport.disconnect_client."""

    @pytest.fixture
    def transport(self):
        """Create transport instance with mocked session manager."""
        # Arrange
        transport = HttpServerTransport()
        transport._session_manager = Mock()
        return transport

    async def test_disconnect_client_terminates_existing_session(self, transport):
        """Test disconnecting a client with an existing session."""
        # Arrange
        client_id = "test-client-123"
        session_id = "session-456"
        transport._session_manager.get_session_id.return_value = session_id

        # Act
        await transport.disconnect_client(client_id)

        # Assert
        transport._session_manager.get_session_id.assert_called_once_with(client_id)
        transport._session_manager.terminate_session.assert_called_once_with(session_id)

    async def test_disconnect_client_handles_nonexistent_client(self, transport):
        """Test disconnecting a client that doesn't exist."""
        # Arrange
        client_id = "nonexistent-client"
        transport._session_manager.get_session_id.return_value = None

        # Act
        await transport.disconnect_client(client_id)

        # Assert
        transport._session_manager.get_session_id.assert_called_once_with(client_id)
        transport._session_manager.terminate_session.assert_not_called()

    async def test_disconnect_client_handles_empty_session_id(self, transport):
        """Test disconnecting when session ID is empty string."""
        # Arrange
        client_id = "test-client"
        transport._session_manager.get_session_id.return_value = ""

        # Act
        await transport.disconnect_client(client_id)

        # Assert
        transport._session_manager.get_session_id.assert_called_once_with(client_id)
        transport._session_manager.terminate_session.assert_not_called()

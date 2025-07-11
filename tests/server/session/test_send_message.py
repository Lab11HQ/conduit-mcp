from unittest.mock import AsyncMock, Mock

import pytest

from conduit.protocol.base import PROTOCOL_VERSION
from conduit.protocol.common import EmptyResult, PingRequest, ProgressNotification
from conduit.protocol.initialization import Implementation, ServerCapabilities
from conduit.protocol.tools import ListToolsRequest
from conduit.server.session import ServerConfig, ServerSession


class TestSendMessage:
    """Test server session send message methods."""

    def setup_method(self):
        self.transport = Mock()
        self.config = ServerConfig(
            capabilities=ServerCapabilities(),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )

    async def test_send_notification_to_client_delegates_to_coordinator(self):
        # Arrange
        session = ServerSession(self.transport, self.config)
        client_id = "test-client"
        notification = ProgressNotification(
            progress_token="progress-123", progress=75, total=100
        )

        # Mock the coordinator
        session._coordinator.send_notification_to_client = AsyncMock()

        # Act
        await session.send_notification_to_client(client_id, notification)

        # Assert
        session._coordinator.send_notification_to_client.assert_awaited_once_with(
            client_id, notification
        )

    async def test_send_notification_to_client_propagates_connection_error(self):
        # Arrange
        session = ServerSession(self.transport, self.config)
        client_id = "test-client"
        notification = ProgressNotification(
            progress_token="progress-123", progress=75, total=100
        )

        # Mock the coordinator to raise ConnectionError
        session._coordinator.send_notification_to_client = AsyncMock(
            side_effect=ConnectionError("Transport is closed")
        )

        # Act & Assert - should propagate the exception
        with pytest.raises(ConnectionError, match="Transport is closed"):
            await session.send_notification_to_client(client_id, notification)

    async def test_send_request_to_client_delegates_to_coordinator(self):
        # Arrange
        session = ServerSession(self.transport, self.config)
        client_id = "test-client"
        request = PingRequest()

        # Register and initialize client
        session.client_manager.register_client(client_id)
        client_context = session.client_manager.get_client(client_id)
        client_context.initialized = True

        # Mock successful coordinator response
        expected_result = EmptyResult()
        session._coordinator.send_request_to_client = AsyncMock(
            return_value=expected_result
        )

        # Act
        result = await session.send_request_to_client(client_id, request)

        # Assert
        assert result == expected_result
        session._coordinator.send_request_to_client.assert_awaited_once_with(
            client_id, request, 30.0
        )

    async def test_send_request_to_client_propagates_coordinator_error(self):
        # Arrange
        session = ServerSession(self.transport, self.config)
        client_id = "test-client"
        request = PingRequest()

        # Mock coordinator to raise error
        session._coordinator.send_request_to_client = AsyncMock(
            side_effect=ConnectionError("Test error")
        )

        # Act & Assert - should propagate the exception
        with pytest.raises(ConnectionError, match="Test error"):
            await session.send_request_to_client(client_id, request)

    async def test_send_request_to_client_raises_value_error_for_uninitialized_client(
        self,
    ):
        # Arrange
        session = ServerSession(self.transport, self.config)
        client_id = "test-client"
        request = ListToolsRequest()  # Non-ping request

        # Register client but don't initialize
        session.client_manager.register_client(client_id)

        # Act & Assert - should raise ValueError for uninitialized client
        with pytest.raises(
            ValueError,
            match="Cannot send tools/list to uninitialized client test-client",
        ):
            await session.send_request_to_client(client_id, request)

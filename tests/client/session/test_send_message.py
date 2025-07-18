from unittest.mock import AsyncMock

import pytest

from conduit.client.session_v2 import ClientConfig, ClientSession
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializedNotification,
    InitializeRequest,
)
from conduit.protocol.tools import ListToolsRequest


class TestSendMessage:
    """Test session-specific request filtering logic."""

    def setup_method(self):
        self.transport = AsyncMock()
        self.config = ClientConfig(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(),
        )
        self.session = ClientSession(self.transport, self.config)

        # Mock both coordinator methods to avoid transport interaction
        self.session._coordinator.start = AsyncMock()
        self.session._coordinator.send_request = AsyncMock()
        self.session._coordinator.send_notification = AsyncMock()

    async def test_allows_initialize_request_to_uninitialized_server(self):
        """Test that initialize requests are allowed to uninitialized servers."""
        # Arrange
        server_id = "test-server"
        request = InitializeRequest(
            protocol_version="2024-11-05",
            client_info=self.config.client_info,
            capabilities=self.config.capabilities,
        )

        # Server is not registered/initialized

        # Act
        await self.session.send_request(server_id, request)

        # Assert
        self.session._coordinator.send_request.assert_awaited_once_with(
            server_id, request, 30.0
        )

    async def test_allows_regular_request_to_initialized_server(self):
        """Test that regular requests are allowed to initialized servers."""
        # Arrange
        server_id = "test-server"
        request = ListToolsRequest()

        # Register and mark server as initialized
        self.session.server_manager.register_server(server_id)
        self.session.server_manager.get_server(server_id).initialized = True

        # Act
        await self.session.send_request(server_id, request)

        # Assert
        self.session._coordinator.send_request.assert_awaited_once_with(
            server_id, request, 30.0
        )

    async def test_raises_error_for_regular_request_to_uninitialized_server(self):
        """Test that regular requests to uninitialized servers raise ValueError."""
        # Arrange
        server_id = "test-server"
        request = ListToolsRequest()
        self.session.server_manager.register_server(server_id)
        assert not self.session.server_manager.is_protocol_initialized(server_id)

        # Act & Assert
        with pytest.raises(ValueError):
            await self.session.send_request(server_id, request)

        # Coordinator should not be called
        self.session._coordinator.send_request.assert_not_awaited()

    async def test_send_notification_delegates_to_coordinator(self):
        """Test that send_notification delegates to coordinator."""
        # Arrange
        server_id = "test-server"
        notification = InitializedNotification()

        # Act
        await self.session.send_notification(server_id, notification)

        # Assert
        self.session._coordinator.send_notification.assert_awaited_once_with(
            server_id, notification
        )

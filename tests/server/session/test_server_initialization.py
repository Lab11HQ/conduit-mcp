from conduit.protocol.base import PROTOCOL_VERSION
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
)

from .conftest import ServerSessionTest


class TestInitialization(ServerSessionTest):
    async def test_handle_initialize_stores_client_state(self):
        """Test that _handle_initialize properly stores client information."""
        # Arrange
        client_capabilities = ClientCapabilities(
            sampling=True,
            elicitation=True,
            roots={"listChanged": True},
        )
        request = InitializeRequest(
            client_info=Implementation(name="test-client", version="2.1.0"),
            capabilities=client_capabilities,
            protocol_version=PROTOCOL_VERSION,
        )

        # Act
        result = await self.session._handle_initialize(request)

        # Assert
        assert isinstance(result, InitializeResult)

        # Verify client state was stored
        assert self.session.client_state.capabilities == client_capabilities
        assert self.session.client_state.info.name == "test-client"
        assert self.session.client_state.info.version == "2.1.0"
        assert self.session.client_state.protocol_version == PROTOCOL_VERSION

    async def test_handle_initialize_returns_result_with_server_config(self):
        """Test that _handle_initialize returns server configuration."""
        # Arrange
        request = InitializeRequest(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(),
        )

        # Act
        result = await self.session._handle_initialize(request)

        # Assert
        assert isinstance(result, InitializeResult)
        assert result.server_info == self.session.server_config.info
        assert result.capabilities == self.session.server_config.capabilities
        assert result.protocol_version == self.session.server_config.protocol_version
        assert result.instructions == self.session.server_config.instructions

    async def test_initialization_state_tracking(self):
        """Test that initialization state is properly tracked."""
        # Arrange
        assert self.session.initialized is False

        # Act - handle initialize request
        request = InitializeRequest(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(),
        )
        await self.session._handle_initialize(request)

        # Assert - still not initialized until we get the notification
        assert self.session.initialized is False

        # Act - handle initialized notification
        notification = InitializedNotification()
        await self.session._handle_initialized(notification)

        # Assert - now we're initialized
        assert self.session.initialized is True

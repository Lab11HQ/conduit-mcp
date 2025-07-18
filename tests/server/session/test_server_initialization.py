from unittest.mock import Mock

from conduit.protocol.base import (
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_MISMATCH,
    Error,
)
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializeRequest,
    InitializeResult,
    ServerCapabilities,
)
from conduit.server.session import ServerConfig, ServerSession


class TestInitialization:
    """Test server session initialization handling."""

    def setup_method(self):
        self.transport = Mock()
        self.config = ServerConfig(
            capabilities=ServerCapabilities(),
            info=Implementation(name="test-server", version="1.0.0"),
        )
        self.session = ServerSession(self.transport, self.config)

        self.valid_request = InitializeRequest(
            capabilities=ClientCapabilities(),
            client_info=Implementation(name="test-client", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )

    async def test_registers_client_when_protocol_version_matches(self):
        # Arrange
        client_id = "test-client-123"

        # Act
        result = await self.session._handle_initialize(client_id, self.valid_request)

        # Assert
        assert isinstance(result, InitializeResult)
        assert result.capabilities == self.config.capabilities
        assert result.server_info == self.config.info
        assert result.protocol_version == self.config.protocol_version

        # Verify client was registered and initialized
        assert self.session.client_manager.is_protocol_initialized(client_id)
        state = self.session.client_manager.get_client(client_id)
        assert state.capabilities == self.valid_request.capabilities
        assert state.info == self.valid_request.client_info

    async def test_does_not_register_client_when_protocol_version_does_not_match(self):
        # Arrange
        client_id = "test-client-456"
        mismatched_request = InitializeRequest(
            capabilities=ClientCapabilities(),
            client_info=Implementation(name="test-client", version="1.0.0"),
            protocol_version="2024-01-01",
        )

        # Act
        result = await self.session._handle_initialize(client_id, mismatched_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == PROTOCOL_VERSION_MISMATCH

        # Verify no client state was created (since initialization failed)
        state = self.session.client_manager.get_client(client_id)
        assert state is None

    async def test_cannot_reinitialize_client(self):
        # Arrange
        client_id = "test-client-789"

        # First initialization succeeds
        result1 = await self.session._handle_initialize(client_id, self.valid_request)
        assert isinstance(result1, InitializeResult)
        assert self.session.client_manager.is_protocol_initialized(client_id)

        # Act - attempt to initialize again
        result2 = await self.session._handle_initialize(client_id, self.valid_request)

        # Assert
        assert isinstance(result2, Error)
        assert result2.code == METHOD_NOT_FOUND

        # Verify client state unchanged
        assert self.session.client_manager.is_protocol_initialized(client_id)

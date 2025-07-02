import asyncio

import pytest

from conduit.client.session import InvalidProtocolVersionError
from conduit.protocol.initialization import InitializeResult

from .conftest import ClientSessionTest


class TestInitialization(ClientSessionTest):
    async def test_initialization_handshake_is_successful(self):
        # Arrange
        expected_capabilities = {"tools": {"listChanged": True}}
        assert self.session.initialized is False

        # Act
        init_task = asyncio.create_task(self.session.initialize())
        await self.wait_for_sent_message("initialize")

        request_id = self.transport.sent_messages[0]["id"]
        response = self.create_init_response(
            request_id, capabilities=expected_capabilities
        )
        self.transport.receive_message(response)

        result = await init_task

        # Assert
        assert isinstance(result, InitializeResult)
        assert (
            result.server_info.name == "test-server"
        )  # Default from create_init_response
        assert self.session.initialized is True

        # Verify handshake sequence: initialize request + initialized notification
        assert len(self.transport.sent_messages) == 2
        assert self.transport.sent_messages[0]["method"] == "initialize"
        assert self.transport.sent_messages[1]["method"] == "notifications/initialized"

    async def test_initialization_is_idempotent(self):
        """Test that calling initialize() multiple times returns cached result."""
        # Arrange
        # (First initialization)
        init_task = asyncio.create_task(self.session.initialize())
        await self.wait_for_sent_message("initialize")

        request_id = self.transport.sent_messages[0]["id"]
        response = self.create_init_response(request_id)
        self.transport.receive_message(response)

        result1 = await init_task

        # Act
        result2 = await self.session.initialize()

        # Assert
        assert result1 == result2
        assert len(self.transport.sent_messages) == 2  # Still just init + notification

    async def test_initialization_raises_timeout_when_server_does_not_respond(self):
        """Test initialization timeout when server doesn't respond."""
        # Act & Assert
        with pytest.raises(TimeoutError, match="Initialization timed out after 0.1s"):
            await self.session.initialize(timeout=0.1)

        # Assert cleanup
        assert not self.session.running

    async def test_raises_error_when_server_protocol_version_mismatches(self):
        """Test handling of protocol version mismatch."""
        # Arrange
        init_task = asyncio.create_task(self.session.initialize())
        await self.wait_for_sent_message("initialize")

        request_id = self.transport.sent_messages[0]["id"]
        response = self.create_init_response(
            request_id,
            protocol_version="1.0.0",  # Different version
        )

        # Act & Assert
        self.transport.receive_message(response)

        with pytest.raises(
            InvalidProtocolVersionError, match="Protocol version mismatch"
        ):
            await init_task

        # Assert cleanup
        assert not self.session.running

    async def test_raises_error_when_server_rejects_initialization(self):
        """Test handling of server initialization error."""
        # Arrange
        init_task = asyncio.create_task(self.session.initialize())
        await self.wait_for_sent_message("initialize")

        request_id = self.transport.sent_messages[0]["id"]
        error_response = self.create_init_error(
            request_id, message="Server initialization failed"
        )

        # Act
        self.transport.receive_message(error_response)

        # Assert: Server errors should be wrapped in ConnectionError
        with pytest.raises(ConnectionError):
            await init_task

        # Assert Cleanup
        assert not self.session.running

    async def test_raises_error_when_server_returns_unexpected_response_type(self):
        # Arrange
        init_task = asyncio.create_task(self.session.initialize())
        await self.wait_for_sent_message("initialize")

        request_id = self.transport.sent_messages[0]["id"]
        unexpected_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": "Not an InitializeResult",
        }

        # Act
        self.transport.receive_message(unexpected_response)

        # Assert
        with pytest.raises(ConnectionError):
            await init_task

    async def test_raises_error_when_transport_fails_during_handshake(self):
        """Test handling of transport failure during handshake."""
        # Arrange
        self.transport.simulate_error()

        # Act & Assert
        with pytest.raises(ConnectionError):
            await self.session.initialize()

        # Assert cleanup
        assert not self.session.running

    async def test_updates_server_state_after_successful_initialization(self):
        """Test that server state is properly updated after initialization."""
        # Arrange
        server_capabilities = {
            "tools": {"listChanged": True},
            "resources": {"subscribe": True, "listChanged": False},
            "prompts": {"listChanged": True},
        }

        init_task = asyncio.create_task(self.session.initialize())
        await self.wait_for_sent_message("initialize")

        request_id = self.transport.sent_messages[0]["id"]
        response = self.create_init_response(
            request_id,
            server_name="test-server",
            server_version="2.1.0",
            capabilities=server_capabilities,
            instructions="Welcome to the test server!",
        )

        # Act
        self.transport.receive_message(response)
        await init_task

        # Assert
        assert self.session.server_state.info.name == "test-server"
        assert self.session.server_state.info.version == "2.1.0"
        assert self.session.server_state.instructions == "Welcome to the test server!"
        assert self.session.server_state.capabilities.tools.list_changed is True
        assert self.session.server_state.capabilities.resources.subscribe is True
        assert self.session.server_state.capabilities.resources.list_changed is False

import asyncio
from copy import deepcopy

import pytest

from conduit.client.session import (
    ClientConfig,
    ClientSession,
    InvalidProtocolVersionError,
)
from conduit.protocol.base import METHOD_NOT_FOUND, PROTOCOL_VERSION
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
)

from .conftest import MockClientTransport


class TestInitialization:
    def setup_method(self):
        self.transport = MockClientTransport()
        self.config = ClientConfig(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(),
        )
        self.session = ClientSession(self.transport, self.config)

    init_response_matching_protocol = {
        "jsonrpc": "2.0",
        "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "serverInfo": {
                "name": "test-server",
                "version": "1.0.0",
            },
        },
    }

    init_response_mismatched_protocol = {
        "jsonrpc": "2.0",
        "result": {
            "protocolVersion": "1.0.0",
            "capabilities": {},
            "serverInfo": {
                "name": "test-server",
                "version": "1.0.0",
            },
        },
    }

    init_response_error = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": METHOD_NOT_FOUND, "message": "Server initialization failed"},
    }

    async def test_initialization_handshake_is_successful(self, yield_loop):
        # Arrange
        assert not self.session._initialized

        # Act
        init_task = asyncio.create_task(self.session.initialize())

        # Wait for the initialize request to be sent
        await yield_loop()

        # Simulate server response
        request_id = self.transport.sent_messages[0]["id"]
        response = deepcopy(self.init_response_matching_protocol)
        response["id"] = request_id
        self.transport.receive_message(response)

        await init_task

        # Assert
        assert self.session._initialized

        # Verify handshake sequence: initialize request + initialized notification
        assert len(self.transport.sent_messages) == 2
        assert self.transport.sent_messages[0]["method"] == "initialize"
        assert self.transport.sent_messages[1]["method"] == "notifications/initialized"

        # Verify server state was updated
        server_context = self.session.server_manager.get_server_context()
        assert server_context.initialized
        assert server_context.info.name == "test-server"
        assert server_context.info.version == "1.0.0"

    async def test_initialization_is_idempotent(self, yield_loop):
        """Test that calling initialize() multiple times returns cached result."""
        # Arrange & Act - first initialization
        init_task = asyncio.create_task(self.session.initialize())
        await yield_loop()

        request_id = self.transport.sent_messages[0]["id"]
        response = deepcopy(self.init_response_matching_protocol)
        response["id"] = request_id
        self.transport.receive_message(response)

        await init_task
        assert self.session._initialized

        # Act - second initialization should not send a new request
        await self.session.initialize()
        await yield_loop()

        # Assert
        assert (
            len(self.transport.sent_messages) == 2
        )  # Only init request + notification
        assert self.session._initialized

    async def test_initialization_raises_timeout_when_server_does_not_respond(self):
        """Test initialization timeout when server doesn't respond."""
        # Act & Assert
        with pytest.raises(TimeoutError, match="Initialization timed out after 0.1s"):
            await self.session.initialize(timeout=0.1)

    async def test_raises_error_when_server_protocol_version_mismatches(
        self, yield_loop
    ):
        """Test handling of protocol version mismatch."""
        # Arrange
        init_task = asyncio.create_task(self.session.initialize())
        await yield_loop()

        request_id = self.transport.sent_messages[0]["id"]
        response = deepcopy(self.init_response_mismatched_protocol)
        response["id"] = request_id

        # Act & Assert
        self.transport.receive_message(response)

        with pytest.raises(
            InvalidProtocolVersionError, match="Protocol version mismatch"
        ):
            await init_task

    async def test_raises_error_when_server_rejects_initialization(self, yield_loop):
        """Test handling of server initialization error."""
        # Arrange
        init_task = asyncio.create_task(self.session.initialize())
        await yield_loop()

        request_id = self.transport.sent_messages[0]["id"]
        error_response = deepcopy(self.init_response_error)
        error_response["id"] = request_id

        # Act
        self.transport.receive_message(error_response)

        # Assert: Server errors should be wrapped in ConnectionError
        with pytest.raises(ConnectionError):
            await init_task

    async def test_raises_error_when_transport_fails_during_handshake(self):
        """Test handling of transport failure during handshake."""
        # Arrange
        self.transport.simulate_error()

        # Act & Assert
        with pytest.raises(ConnectionError):
            await self.session.initialize()

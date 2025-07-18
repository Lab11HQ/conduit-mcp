import asyncio
from copy import deepcopy

import pytest

from conduit.client.session_v2 import (
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

    async def test_connect_server_handshake_is_successful(self, yield_loop):
        # Arrange
        server_id = "test-server"
        connection_info = {"host": "test-host", "port": 8080}

        # Verify server is not initialized yet
        assert not self.session.server_manager.is_protocol_initialized(server_id)

        # Act
        connect_task = asyncio.create_task(
            self.session.connect_server(server_id, connection_info)
        )

        # Wait for the initialize request to be sent
        await yield_loop()

        # Simulate server response
        sent_messages = self.transport.sent_messages.get(server_id, [])
        assert len(sent_messages) == 1
        request_id = sent_messages[0]["id"]

        response = deepcopy(self.init_response_matching_protocol)
        response["id"] = request_id
        self.transport.add_server_message(server_id, response)

        await connect_task

        # Assert
        assert self.session.server_manager.is_protocol_initialized(server_id)

        # Verify handshake sequence: initialize request + initialized notification
        sent_messages = self.transport.sent_messages.get(server_id, [])
        assert len(sent_messages) == 2
        assert sent_messages[0]["method"] == "initialize"
        assert sent_messages[1]["method"] == "notifications/initialized"

        # Verify server state was updated
        server_state = self.session.server_manager.get_server(server_id)
        assert server_state is not None
        assert server_state.initialized
        assert server_state.info.name == "test-server"
        assert server_state.info.version == "1.0.0"

        await self.session.disconnect_all_servers()

    async def test_connect_server_is_idempotent(self, yield_loop):
        """Test that calling connect_server() multiple times returns cached result."""
        # Arrange
        server_id = "test-server"
        connection_info = {"host": "test-host", "port": 8080}

        # Act - first connection
        connect_task = asyncio.create_task(
            self.session.connect_server(server_id, connection_info)
        )
        await yield_loop()

        # Simulate server response
        sent_messages = self.transport.sent_messages.get(server_id, [])
        assert len(sent_messages) == 1
        request_id = sent_messages[0]["id"]

        response = deepcopy(self.init_response_matching_protocol)
        response["id"] = request_id
        self.transport.add_server_message(server_id, response)

        await connect_task
        assert self.session.server_manager.is_protocol_initialized(server_id)

        # Act - second connection should not send a new request
        await self.session.connect_server(server_id, connection_info)
        await yield_loop()

        # Assert - still only 2 messages (init request + notification)
        sent_messages = self.transport.sent_messages.get(server_id, [])
        assert len(sent_messages) == 2  # Only init request + notification
        assert self.session.server_manager.is_protocol_initialized(server_id)

        await self.session.disconnect_all_servers()

    async def test_connect_server_raises_timeout_when_server_does_not_respond(self):
        """Test connection timeout when server doesn't respond."""
        # Arrange
        server_id = "test-server"
        connection_info = {"host": "test-host", "port": 8080}

        # Act & Assert
        with pytest.raises(TimeoutError):
            await self.session.connect_server(server_id, connection_info, timeout=0.1)

    async def test_raises_error_when_server_protocol_version_mismatches(
        self, yield_loop
    ):
        """Test handling of protocol version mismatch."""
        # Arrange
        server_id = "test-server"
        connection_info = {"host": "test-host", "port": 8080}

        connect_task = asyncio.create_task(
            self.session.connect_server(server_id, connection_info)
        )
        await yield_loop()

        # Simulate server response with mismatched protocol
        sent_messages = self.transport.sent_messages.get(server_id, [])
        assert len(sent_messages) == 1
        request_id = sent_messages[0]["id"]

        response = deepcopy(self.init_response_mismatched_protocol)
        response["id"] = request_id
        self.transport.add_server_message(server_id, response)

        # Act & Assert
        with pytest.raises(InvalidProtocolVersionError):
            await connect_task

    async def test_raises_error_when_server_rejects_initialization(self, yield_loop):
        """Test handling of server initialization error."""
        # Arrange
        server_id = "test-server"
        connection_info = {"host": "test-host", "port": 8080}

        connect_task = asyncio.create_task(
            self.session.connect_server(server_id, connection_info)
        )
        await yield_loop()

        # Simulate server error response
        sent_messages = self.transport.sent_messages.get(server_id, [])
        assert len(sent_messages) == 1
        request_id = sent_messages[0]["id"]

        error_response = deepcopy(self.init_response_error)
        error_response["id"] = request_id
        self.transport.add_server_message(server_id, error_response)

        # Act & Assert: Server errors should be wrapped in ConnectionError
        with pytest.raises(ConnectionError):
            await connect_task

    async def test_raises_error_when_transport_fails_during_handshake(self):
        """Test handling of transport failure during handshake."""
        # Arrange
        server_id = "test-server"
        connection_info = {"host": "test-host", "port": 8080}
        self.transport.simulate_error()

        # Act & Assert
        with pytest.raises(ConnectionError):
            await self.session.connect_server(server_id, connection_info)

    async def test_raises_error_when_server_returns_unexpected_response(
        self, yield_loop
    ):
        """Test handling when server returns neither Error nor InitializeResult."""
        # Arrange
        server_id = "test-server"
        connection_info = {"host": "test-host", "port": 8080}

        connect_task = asyncio.create_task(
            self.session.connect_server(server_id, connection_info)
        )
        await yield_loop()

        # Simulate server returning something weird (not Error or InitializeResult)
        sent_messages = self.transport.sent_messages.get(server_id, [])
        request_id = sent_messages[0]["id"]

        weird_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": "this is not an InitializeResult",
        }
        self.transport.add_server_message(server_id, weird_response)

        # Act & Assert
        with pytest.raises(ConnectionError):  # Should be wrapped
            await connect_task

    async def test_raises_error_when_transport_add_server_fails(self):
        """Test handling when transport fails to add server."""
        # Arrange
        server_id = "duplicate-server"
        connection_info = {"host": "test-host", "port": 8080}

        # Pre-register the server to cause add_server to fail
        await self.transport.add_server(server_id, connection_info)

        # Act & Assert
        with pytest.raises(ConnectionError):
            await self.session.connect_server(server_id, connection_info)

    async def test_cleans_up_server_state_on_failure(self, yield_loop):
        """Test that server state is cleaned up when connection fails."""
        # Arrange
        server_id = "test-server"
        connection_info = {"host": "test-host", "port": 8080}

        connect_task = asyncio.create_task(
            self.session.connect_server(server_id, connection_info)
        )
        await yield_loop()

        # Simulate server error
        sent_messages = self.transport.sent_messages.get(server_id, [])
        request_id = sent_messages[0]["id"]
        error_response = deepcopy(self.init_response_error)
        error_response["id"] = request_id
        self.transport.add_server_message(server_id, error_response)

        # Act
        with pytest.raises(ConnectionError):
            await connect_task

        # Assert - server should be cleaned up
        assert self.session.server_manager.get_server(server_id) is None
        assert server_id not in self.transport.registered_servers

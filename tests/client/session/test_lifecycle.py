from unittest.mock import AsyncMock, Mock

from src.conduit.client.session import ClientConfig, ClientSession
from src.conduit.protocol.initialization import ClientCapabilities, Implementation
from tests.client.session.conftest import MockClientTransport


class TestDisconnect:
    def setup_method(self):
        self.transport = MockClientTransport()
        self.config = ClientConfig(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(),
        )
        self.session = ClientSession(self.transport, self.config)

    async def test_disconnect_server_cleans_up_state(self):
        # Arrange
        server_id = "test-server"
        self.session.server_manager.register_server(server_id)
        await self.transport.add_server(server_id, {"host": "test-host", "port": 8080})

        # Mock the cleanup methods
        self.session.roots.cleanup_server = Mock()
        self.session.transport.disconnect_server = AsyncMock()

        # Act
        await self.session.disconnect_server(server_id)

        # Assert - verify all cleanup methods were called
        self.session.roots.cleanup_server.assert_called_once_with(server_id)
        self.session.transport.disconnect_server.assert_awaited_once_with(server_id)

        # Assert - verify server manager cleanup (observable state)
        assert server_id not in self.session.server_manager.get_server_ids()

    async def test_disconnect_server_is_idempotent(self):
        # Arrange
        server_id = "test-server"
        self.session.server_manager.register_server(server_id)
        await self.transport.add_server(server_id, {"host": "test-host", "port": 8080})

        # Act - calling twice should not raise
        await self.session.disconnect_server(server_id)
        await self.session.disconnect_server(server_id)

        # Assert - final state is clean
        assert server_id not in self.session.server_manager.get_server_ids()

    async def test_disconnect_server_completes_cleanup_even_if_transport_fails(self):
        # Arrange
        server_id = "test-server"
        self.session.server_manager.register_server(server_id)
        await self.transport.add_server(server_id, {"host": "test-host", "port": 8080})

        # Mock cleanup methods - roots succeeds, transport fails
        self.session.roots.cleanup_server = Mock()
        self.session.transport.disconnect_server = AsyncMock(
            side_effect=ConnectionError("Transport failed")
        )

        # Act - should not raise despite transport failure
        await self.session.disconnect_server(server_id)

        # Assert - manager cleanup still happened
        self.session.roots.cleanup_server.assert_called_once_with(server_id)
        self.session.transport.disconnect_server.assert_awaited_once_with(server_id)

        # Assert - server manager cleanup completed (observable state)
        assert server_id not in self.session.server_manager.get_server_ids()

    async def test_disconnect_all_servers_removes_all_servers(self):
        # Arrange - register multiple servers
        server_ids = ["server-1", "server-2"]
        for server_id in server_ids:
            self.session.server_manager.register_server(server_id)
            await self.transport.add_server(
                server_id, {"host": "test-host", "port": 8080}
            )

        # Act
        await self.session.disconnect_all_servers()

        # Assert - all servers removed
        assert self.session.server_manager.get_server_ids() == []

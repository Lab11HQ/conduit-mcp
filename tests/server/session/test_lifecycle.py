from unittest.mock import AsyncMock, Mock

from src.conduit.protocol.initialization import Implementation, ServerCapabilities
from src.conduit.server.session import ServerConfig, ServerSession
from tests.server.session.conftest import MockServerTransport


class TestDisconnect:
    def setup_method(self):
        self.transport = MockServerTransport()
        self.session = ServerSession(
            transport=self.transport,
            config=ServerConfig(
                info=Implementation(name="test-server", version="1.0.0"),
                capabilities=ServerCapabilities(),
            ),
        )

    async def test_disconnect_client_cleans_up_state(self):
        # Arrange
        client_id = "test-client"
        self.session.client_manager.register_client(client_id)

        # Mock the cleanup methods
        self.session.tools.cleanup_client = Mock()
        self.session.resources.cleanup_client = Mock()
        self.session.prompts.cleanup_client = Mock()
        self.session.logging.cleanup_client = Mock()
        self.session.transport.disconnect_client = AsyncMock()

        # Act
        await self.session.disconnect_client(client_id)

        # Assert - verify all cleanup methods were called
        self.session.tools.cleanup_client.assert_called_once_with(client_id)
        self.session.resources.cleanup_client.assert_called_once_with(client_id)
        self.session.prompts.cleanup_client.assert_called_once_with(client_id)
        self.session.logging.cleanup_client.assert_called_once_with(client_id)
        self.session.transport.disconnect_client.assert_awaited_once_with(client_id)

        # Assert - verify client manager cleanup (observable state)
        assert client_id not in self.session.client_manager.get_client_ids()

    async def test_disconnect_client_is_idempotent(self):
        # Arrange
        client_id = "test-client"
        self.session.client_manager.register_client(client_id)

        # Act - calling twice should not raise
        await self.session.disconnect_client(client_id)
        await self.session.disconnect_client(client_id)

        # Assert - final state is clean
        assert client_id not in self.session.client_manager.get_client_ids()

    async def test_disconnect_client_completes_cleanup_even_if_transport_fails(self):
        # Arrange
        client_id = "test-client"
        self.session.client_manager.register_client(client_id)

        # Mock cleanup methods - managers succeed, transport fails
        self.session.tools.cleanup_client = Mock()
        self.session.resources.cleanup_client = Mock()
        self.session.prompts.cleanup_client = Mock()
        self.session.logging.cleanup_client = Mock()
        self.session.transport.disconnect_client = AsyncMock(
            side_effect=ConnectionError("Transport failed")
        )

        # Act - should not raise despite transport failure
        await self.session.disconnect_client(client_id)

        # Assert - manager cleanup still happened
        self.session.tools.cleanup_client.assert_called_once_with(client_id)
        self.session.resources.cleanup_client.assert_called_once_with(client_id)
        self.session.prompts.cleanup_client.assert_called_once_with(client_id)
        self.session.logging.cleanup_client.assert_called_once_with(client_id)
        self.session.transport.disconnect_client.assert_awaited_once_with(client_id)

        # Assert - client manager cleanup completed (observable state)
        assert client_id not in self.session.client_manager.get_client_ids()

    async def test_disconnect_all_clients_removes_all_clients(self):
        # Arrange - register multiple clients
        client_ids = ["client-1", "client-2"]
        for client_id in client_ids:
            self.session.client_manager.register_client(client_id)

        # Act
        await self.session.disconnect_all_clients()

        # Assert - all clients removed
        assert self.session.client_manager.get_client_ids() == []

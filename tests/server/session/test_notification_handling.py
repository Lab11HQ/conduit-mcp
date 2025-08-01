from unittest.mock import AsyncMock, Mock

from conduit.protocol.base import PROTOCOL_VERSION
from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.protocol.initialization import Implementation, ServerCapabilities
from conduit.protocol.roots import ListRootsResult, Root, RootsListChangedNotification
from conduit.server.client_manager import ClientState
from conduit.server.request_context import RequestContext
from conduit.server.session import ServerConfig, ServerSession


class TestNotificationHandling:
    """Test server session notification handling."""

    def setup_method(self):
        self.transport = Mock()
        self.config = ServerConfig(
            capabilities=ServerCapabilities(),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )
        self.context = RequestContext(
            client_id="test-client",
            client_state=ClientState(),
            client_manager=AsyncMock(),
            transport=self.transport,
        )

    async def test_handle_cancelled_processes_cancellation_notification(self):
        # Arrange
        session = ServerSession(self.transport, self.config)
        # Need to register client to untrack request. Otherwise we'll get a ValueError
        # for trying to untrack a request with an unregistered client.
        session.client_manager.register_client(self.context.client_id)
        notification = CancelledNotification(request_id="req-123")

        # Mock only the callback (the observable behavior)
        session.callbacks.call_cancelled = AsyncMock()

        # Act
        await session._handle_cancelled(self.context, notification)

        # Assert
        session.callbacks.call_cancelled.assert_awaited_once_with(
            self.context.client_id, notification
        )

    async def test_handle_progress_calls_callback(self):
        # Arrange
        session = ServerSession(self.transport, self.config)
        notification = ProgressNotification(
            progress_token="progress-123", progress=50, total=100
        )

        # Mock the callbacks
        session.callbacks.call_progress = AsyncMock()

        # Act
        await session._handle_progress(self.context, notification)

        # Assert
        session.callbacks.call_progress.assert_awaited_once_with(
            self.context.client_id, notification
        )

    async def test_handle_roots_list_changed_updates_client_state_and_calls_callback(
        self,
    ):
        # Arrange
        session = ServerSession(self.transport, self.config)
        notification = RootsListChangedNotification()

        # Register client to create state
        session.client_manager.register_client(self.context.client_id)

        # Mock successful coordinator response
        new_roots = [
            Root(uri="file:///home/user/project", name="Project"),
            Root(uri="file:///home/user/docs", name="Documents"),
        ]
        list_roots_result = ListRootsResult(roots=new_roots)
        session.send_request = AsyncMock(return_value=list_roots_result)

        # Mock callback
        session.callbacks.call_roots_changed = AsyncMock()

        # Act
        await session._handle_roots_list_changed(self.context, notification)

        # Assert - verify client state was updated
        state = session.client_manager.get_client(self.context.client_id)
        assert state.roots == new_roots

        # Assert - verify callback was called with client state
        session.callbacks.call_roots_changed.assert_awaited_once_with(
            self.context.client_id, new_roots
        )

    async def test_transport_error_does_not_propagate_when_roots_list_changed(self):
        # Arrange
        session = ServerSession(self.transport, self.config)
        notification = RootsListChangedNotification()

        # Register client to create state
        session.client_manager.register_client(self.context.client_id)

        # Mock coordinator to raise exception
        session.send_request = AsyncMock(side_effect=Exception("Transport error"))

        # Mock callback (should not be called)
        session.callbacks.call_roots_changed = AsyncMock()

        # Act - should not raise exception
        await session._handle_roots_list_changed(self.context, notification)

        # Assert - callback should not be called on error
        session.callbacks.call_roots_changed.assert_not_awaited()

    async def test_handle_roots_list_changed_does_not_propagate_callback_exception(
        self,
    ):
        # Arrange
        session = ServerSession(self.transport, self.config)
        notification = RootsListChangedNotification()

        # Register client to create state
        session.client_manager.register_client(self.context.client_id)

        # Mock successful coordinator response
        new_roots = [Root(uri="file:///home/user/project", name="Project")]
        list_roots_result = ListRootsResult(roots=new_roots)
        session.send_request = AsyncMock(return_value=list_roots_result)

        # Mock callback to raise exception
        session.callbacks.call_roots_changed = AsyncMock(
            side_effect=Exception("Callback failed")
        )

        # Act - should not raise exception despite callback failure
        await session._handle_roots_list_changed(self.context, notification)

        # Assert - client state should still be updated despite callback failure
        state = session.client_manager.get_client(self.context.client_id)
        assert state.roots == new_roots

        # Assert - callback was attempted
        session.callbacks.call_roots_changed.assert_awaited_once_with(
            self.context.client_id, new_roots
        )

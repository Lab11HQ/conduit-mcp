from unittest.mock import AsyncMock, Mock

from conduit.protocol.base import METHOD_NOT_FOUND, Error
from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.protocol.roots import (
    ListRootsRequest,
    ListRootsResult,
    Root,
    RootsListChangedNotification,
)

from .conftest import ServerSessionTest


class TestNotificationRouting(ServerSessionTest):
    async def test_ignores_unknown_notification_method(self):
        """Test that unknown notification methods are silently ignored."""

        # Arrange - create a proper mock notification object
        class UnknownNotification:
            def __init__(self):
                self.method = "notifications/unknown"

        unknown_notification = UnknownNotification()

        # Act - this should not raise an exception
        await self.session._handle_session_notification(unknown_notification)

        # Assert - no exception was raised (test passes if we get here)
        # Unknown notifications are silently ignored
        assert True


class TestCancellationNotificationHandling(ServerSessionTest):
    async def test_cancels_in_flight_request_and_notifies_callback(self):
        # Arrange
        request_id = "test-request-123"
        mock_task = Mock()
        self.session._in_flight_requests[request_id] = mock_task

        cancellation = CancelledNotification(
            request_id=request_id, reason="user cancelled"
        )

        # Mock the callback manager
        self.session.callbacks.call_cancelled = AsyncMock()

        # Act
        await self.session._handle_cancelled(cancellation)

        # Assert
        mock_task.cancel.assert_called_once()
        self.session.callbacks.call_cancelled.assert_awaited_once_with(cancellation)

    async def test_ignores_cancellation_when_request_id_not_found(self):
        # Arrange
        cancellation = CancelledNotification(
            request_id="unknown-request", reason="user cancelled"
        )

        # Mock the callback manager
        self.session.callbacks.call_cancelled = AsyncMock()

        # Act
        await self.session._handle_cancelled(cancellation)

        # Assert
        # No task should be cancelled and no callback should be called
        self.session.callbacks.call_cancelled.assert_not_called()


class TestProgressNotificationHandling(ServerSessionTest):
    async def test_delegates_progress_notification_to_callback_manager(self):
        # Arrange
        progress_notification = ProgressNotification(
            progress_token="test-123", progress=50.0, total=100.0
        )

        self.session.callbacks.call_progress = AsyncMock()

        # Act
        await self.session._handle_progress(progress_notification)

        # Assert
        self.session.callbacks.call_progress.assert_awaited_once_with(
            progress_notification
        )


class TestRootsListChangedHandling(ServerSessionTest):
    async def test_updates_state_and_calls_callback_on_successful_refresh(self):
        # Arrange
        roots = [Root(uri="file:///test")]
        roots_notification = RootsListChangedNotification(roots=roots)

        result = ListRootsResult(roots=roots)
        self.session.send_request = AsyncMock(return_value=result)
        self.session.callbacks.call_roots_changed = AsyncMock()

        # Act
        await self.session._handle_roots_list_changed(roots_notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        sent_request = self.session.send_request.call_args[0][0]
        assert isinstance(sent_request, ListRootsRequest)

        self.session.callbacks.call_roots_changed.assert_awaited_once_with(roots)

        assert self.session.client_state.roots == roots

    async def test_ignores_server_error_response_silently(self):
        # Arrange
        roots_notification = RootsListChangedNotification(
            roots=[Root(uri="file:///test")]
        )
        error_result = Error(code=METHOD_NOT_FOUND, message="Roots not supported")
        self.session.send_request = AsyncMock(return_value=error_result)
        self.session.callbacks.call_roots_changed = AsyncMock()
        initial_roots = self.session.client_state.roots

        # Act
        await self.session._handle_roots_list_changed(roots_notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        assert self.session.client_state.roots == initial_roots
        self.session.callbacks.call_roots_changed.assert_not_called()

    async def test_ignores_request_failure_silently(self):
        # Arrange
        roots_notification = RootsListChangedNotification(
            roots=[Root(uri="file:///test")]
        )
        self.session.send_request = AsyncMock(
            side_effect=ConnectionError("Network failure")
        )
        self.session.callbacks.call_roots_changed = AsyncMock()
        initial_roots = self.session.client_state.roots

        # Act
        await self.session._handle_roots_list_changed(roots_notification)

        # Assert
        self.session.send_request.assert_awaited_once()
        assert self.session.client_state.roots == initial_roots
        self.session.callbacks.call_roots_changed.assert_not_called()

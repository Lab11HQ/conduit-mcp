from unittest.mock import AsyncMock, Mock

import pytest

from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.shared.exceptions import UnknownNotificationError

from .conftest import ServerSessionTest


class TestNotificationRouting(ServerSessionTest):
    async def test_raises_error_for_unknown_notification_method(self):
        # Arrange
        unknown_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/unknown",
            "params": {},
        }

        # Act & Assert
        with pytest.raises(UnknownNotificationError, match="notifications/unknown"):
            await self.session._handle_session_notification(unknown_notification)


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

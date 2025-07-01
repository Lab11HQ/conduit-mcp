from unittest.mock import AsyncMock

from .conftest import BaseSessionTest


class TestNotificationHandling(BaseSessionTest):
    async def test_calls_session_notification_handler_with_payload(self):
        # Arrange
        mock_handler = AsyncMock()
        self.session._handle_session_notification = mock_handler

        notification_payload = {
            "jsonrpc": "2.0",
            "method": "test/notification",
            "params": {},
        }

        # Act
        await self.session._handle_notification(notification_payload)

        # Assert
        mock_handler.assert_awaited_once_with(notification_payload)

    async def test_does_not_crash_on_session_handler_exception(self):
        # Arrange
        mock_handler = AsyncMock(side_effect=ValueError("Handler failed"))
        self.session._handle_session_notification = mock_handler

        notification_payload = {"jsonrpc": "2.0", "method": "failing/notification"}

        # Act - should not raise
        await self.session._handle_notification(notification_payload)

        # Assert - handler was called
        mock_handler.assert_awaited_once_with(notification_payload)

from unittest.mock import AsyncMock, Mock

from conduit.protocol.common import CancelledNotification

from .conftest import BaseSessionTest


class TestNotificationHandling(BaseSessionTest):
    async def test_calls_session_notification_handler_with_parsed_notification(self):
        # Arrange - mock _parse_notification to return a valid notification
        parsed_notification = CancelledNotification(request_id="test-123")
        self.session._parse_notification = Mock(return_value=parsed_notification)

        mock_handler = AsyncMock()
        self.session._handle_session_notification = mock_handler

        notification_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": "test-123"},
        }

        # Act
        await self.session._handle_notification(notification_payload)

        # Assert - handler was called with parsed notification
        mock_handler.assert_awaited_once_with(parsed_notification)

    async def test_ignores_notification_when_parsing_fails(self):
        # Arrange - mock _parse_notification to return None (parse failure)
        self.session._parse_notification = Mock(return_value=None)

        mock_handler = AsyncMock()
        self.session._handle_session_notification = mock_handler

        notification_payload = {"jsonrpc": "2.0", "method": "unknown/notification"}

        # Act
        await self.session._handle_notification(notification_payload)

        # Assert - handler was NOT called
        mock_handler.assert_not_called()

    async def test_does_not_crash_on_session_handler_exception(self):
        # Arrange - mock parsing to succeed, handler to fail
        parsed_notification = CancelledNotification(request_id="test-123")
        self.session._parse_notification = Mock(return_value=parsed_notification)

        mock_handler = AsyncMock(side_effect=ValueError("Handler failed"))
        self.session._handle_session_notification = mock_handler

        notification_payload = {"jsonrpc": "2.0", "method": "notifications/cancelled"}

        # Act - should not raise
        await self.session._handle_notification(notification_payload)

        # Assert - handler was called with parsed notification
        mock_handler.assert_awaited_once_with(parsed_notification)


class TestParseNotification(BaseSessionTest):
    def test_parse_notification_returns_typed_notification_for_valid_payload(self):
        # Arrange
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": "test-123"},
        }

        # Act
        result = self.session._parse_notification(payload)

        # Assert
        assert isinstance(result, CancelledNotification)
        assert result.method == "notifications/cancelled"
        assert result.request_id == "test-123"

    def test_parse_notification_returns_none_for_unknown_method(self):
        """_parse_notification returns None for unknown notification methods."""
        # Arrange
        payload = {"jsonrpc": "2.0", "method": "notifications/unknown", "params": {}}

        # Act
        result = self.session._parse_notification(payload)

        # Assert
        assert result is None

    def test_parse_notification_returns_none_for_malformed_payload(self):
        """_parse_notification returns None for malformed notification payloads."""
        # Arrange - cancelled notification with missing requestId
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {},  # Missing requestId
        }

        # Act
        result = self.session._parse_notification(payload)

        # Assert
        assert result is None

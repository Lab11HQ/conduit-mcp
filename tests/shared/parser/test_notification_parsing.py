from conduit.protocol.common import CancelledNotification
from conduit.shared.message_parser import MessageParser


class TestPayloadValidation:
    def test_returns_true_for_valid_notification(self):
        parser = MessageParser()

        # Valid notification with just method
        valid_basic = {"jsonrpc": "2.0", "method": "notifications/progress"}
        assert parser.is_valid_notification(valid_basic) is True

        # Valid notification with method and params
        valid_with_params = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": "test-123", "reason": "User cancelled"},
        }
        assert parser.is_valid_notification(valid_with_params) is True

        # Valid notification with additional fields
        valid_with_extra = {
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {"level": "info", "message": "Hello"},
            "timestamp": "2024-01-01T00:00:00Z",
        }
        assert parser.is_valid_notification(valid_with_extra) is True

    def test_returns_false_for_invalid_notification(self):
        parser = MessageParser()

        # Missing method field
        missing_method = {"jsonrpc": "2.0", "params": {"some": "data"}}
        assert parser.is_valid_notification(missing_method) is False

        # Has id field (makes it a request, not notification)
        has_id = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "id": "test-123",
        }
        assert parser.is_valid_notification(has_id) is False

        # Has id field even if None
        has_none_id = {"jsonrpc": "2.0", "method": "notifications/progress", "id": None}
        assert parser.is_valid_notification(has_none_id) is False

        # Empty payload
        empty_payload = {}
        assert parser.is_valid_notification(empty_payload) is False


class TestNotificationParsing:
    def test_happy_path_cancelled_notification(self):
        # Arrange
        parser = MessageParser()
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": "test-123", "reason": "User cancelled operation"},
        }

        # Act
        result = parser.parse_notification(payload)

        # Assert
        assert isinstance(result, CancelledNotification)
        assert result.method == "notifications/cancelled"
        assert result.request_id == "test-123"
        assert result.reason == "User cancelled operation"

    def test_unknown_notification_method_returns_none(self):
        # Arrange
        parser = MessageParser()
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/unknown_type",
            "params": {"some": "data"},
        }

        # Act
        result = parser.parse_notification(payload)

        # Assert
        assert result is None

    def test_parsing_failure_returns_none(self):
        # Arrange
        parser = MessageParser()
        # CancelledNotification requires requestId, this will fail parsing
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {
                "reason": "Missing requestId will cause parsing to fail"
                # Missing required requestId field
            },
        }

        # Act
        result = parser.parse_notification(payload)

        # Assert
        assert result is None

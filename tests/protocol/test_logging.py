import pytest
from pydantic import ValidationError

from conduit.protocol.logging import (
    LoggingLevel,
    LoggingMessageNotification,
    SetLevelRequest,
)


class TestLogging:
    def test_set_level_request_roundtrip(self):
        request = SetLevelRequest(level=LoggingLevel.DEBUG)
        protocol_data = request.to_protocol()
        assert protocol_data == {
            "method": "logging/setLevel",
            "params": {"level": "debug"},
        }
        assert SetLevelRequest.from_protocol(protocol_data) == request

    def test_logging_message_notification_roundtrip(self):
        notification = LoggingMessageNotification(level=LoggingLevel.DEBUG, data="test")
        protocol_data = notification.to_protocol()
        assert protocol_data == {
            "method": "notifications/message",
            "params": {"level": "debug", "data": "test"},
        }
        assert LoggingMessageNotification.from_protocol(protocol_data) == notification

    def test_request_rejects_invalid_level(self):
        with pytest.raises(ValidationError):
            SetLevelRequest(level="invalid")  # type: ignore

    def test_request_rejects_invalid_level_from_protocol(self):
        with pytest.raises(ValidationError):
            SetLevelRequest.from_protocol(
                {"method": "logging/setLevel", "params": {"level": "BAD_LEVEL"}}
            )

    def test_notification_rejects_invalid_level(self):
        with pytest.raises(ValidationError):
            LoggingMessageNotification(level="invalid", data="test")  # type: ignore

    def test_notification_rejects_invalid_data_from_protocol(self):
        with pytest.raises(ValidationError):
            LoggingMessageNotification.from_protocol(
                {
                    "method": "notifications/message",
                    "params": {"level": "BAD_LEVEL", "data": 123},
                }
            )

    def test_logging_message_notification_normalizes_level(self):
        # Arrange
        notification = LoggingMessageNotification(level="DEBUG", data="test")
        # Assert
        assert notification.level == "debug"

    def test_set_level_request_normalizes_level(self):
        # Arrange
        request = SetLevelRequest(level="DEBUG")
        # Assert
        assert request.level == "debug"

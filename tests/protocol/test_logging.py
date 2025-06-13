import pytest
from pydantic import ValidationError

from conduit.protocol.logging import (
    LoggingMessageNotification,
    SetLevelRequest,
)


class TestLogging:
    def test_set_level_request_roundtrip(self):
        request = SetLevelRequest(level="debug")
        protocol_data = request.to_protocol()
        assert protocol_data == {
            "method": "logging/setLevel",
            "params": {"level": "debug"},
        }
        assert SetLevelRequest.from_protocol(protocol_data) == request

    def test_logging_message_notification_roundtrip(self):
        notification = LoggingMessageNotification(level="debug", data="test")
        protocol_data = notification.to_protocol()
        assert protocol_data == {
            "method": "notifications/message",
            "params": {"level": "debug", "data": "test"},
        }
        assert LoggingMessageNotification.from_protocol(protocol_data) == notification

    def test_request_rejects_invalid_level(self):
        with pytest.raises(ValidationError):
            SetLevelRequest(level="invalid")

    def test_request_rejects_invalid_level_from_protocol(self):
        with pytest.raises(ValidationError):
            SetLevelRequest.from_protocol(
                {"method": "logging/setLevel", "params": {"level": "BAD_LEVEL"}}
            )

    def test_notification_rejects_invalid_level(self):
        with pytest.raises(ValidationError):
            LoggingMessageNotification(level="invalid", data="test")

    def test_notification_rejects_invalid_data_from_protocol(self):
        with pytest.raises(ValidationError):
            LoggingMessageNotification.from_protocol(
                {
                    "method": "notifications/message",
                    "params": {"level": "BAD_LEVEL", "data": 123},
                }
            )

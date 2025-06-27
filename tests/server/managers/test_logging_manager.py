from unittest.mock import AsyncMock

import pytest

from conduit.protocol.common import EmptyResult
from conduit.protocol.logging import SetLevelRequest
from conduit.server.managers.logging import LoggingManager


class TestLoggingManager:
    async def test_handle_set_level_updates_current_level(self):
        # Arrange
        manager = LoggingManager()
        request = SetLevelRequest(level="info")

        # Act
        result = await manager.handle_set_level(request)

        # Assert
        assert manager.current_level == "info"
        assert isinstance(result, EmptyResult)

    async def test_handle_set_level_calls_callback_if_registered(self):
        # Arrange
        manager = LoggingManager()
        callback = AsyncMock()
        manager.set_handler(callback)
        request = SetLevelRequest(level="warning")

        # Act
        await manager.handle_set_level(request)

        # Assert
        callback.assert_awaited_once_with("warning")

    async def test_handle_set_level_silent_if_no_callback_registered(self):
        # Arrange
        manager = LoggingManager()
        request = SetLevelRequest(level="error")

        # Act & Assert - should complete without raising
        result = await manager.handle_set_level(request)
        assert isinstance(result, EmptyResult)

    def test_should_send_log_returns_false_if_no_level_set(self):
        # Arrange
        manager = LoggingManager()

        # Act
        result = manager.should_send_log("info")

        # Assert
        assert result is False

    @pytest.mark.parametrize(
        "current_level,message_level,expected",
        [
            ("debug", "debug", True),
            ("debug", "info", True),
            ("debug", "emergency", True),
            ("info", "debug", False),
            ("info", "info", True),
            ("info", "warning", True),
            ("warning", "info", False),
            ("warning", "warning", True),
            ("emergency", "critical", False),
            ("emergency", "emergency", True),
        ],
    )
    def test_should_send_log_respects_priority_levels(
        self, current_level, message_level, expected
    ):
        # Arrange
        manager = LoggingManager()
        manager.current_level = current_level

        # Act
        result = manager.should_send_log(message_level)

        # Assert
        assert result is expected

from unittest.mock import AsyncMock

from conduit.protocol.base import METHOD_NOT_FOUND, Error
from conduit.protocol.common import EmptyResult
from conduit.protocol.logging import SetLevelRequest

from .conftest import ServerSessionTest


class TestSetLevel(ServerSessionTest):
    async def test_sets_level_when_capability_enabled(self):
        """Test successful log level setting when logging capability is enabled."""
        # Arrange
        self.config.capabilities.logging = True  # Enable logging

        # Mock the manager to return success
        self.session.logging.handle_set_level = AsyncMock(return_value=EmptyResult())

        request = SetLevelRequest(level="info")

        # Act
        result = await self.session._handle_set_level(request)

        # Assert
        assert isinstance(result, EmptyResult)

        # Verify manager was called
        self.session.logging.handle_set_level.assert_awaited_once_with(request)

    async def test_rejects_set_level_when_capability_not_set(self):
        """Test error when logging capability is not configured."""
        # Arrange
        self.config.capabilities.logging = False  # No logging capability
        request = SetLevelRequest(level="debug")

        # Act
        result = await self.session._handle_set_level(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support logging capability"

    async def test_callback_failures_do_not_cause_protocol_errors(self):
        """Test that on_level_change callback failures don't fail the request.

        This documents our design decision that callback failures are logged
        but don't cause protocol errors, since the core operation (setting level)
        succeeds.
        """
        # Arrange
        self.config.capabilities.logging = True  # Enable capability
        assert self.session.logging.current_level is None

        # Set up a failing callback
        failing_callback = AsyncMock(side_effect=ValueError("Callback failed"))
        self.session.logging.on_level_change(failing_callback)

        request = SetLevelRequest(level="info")

        # Act
        result = await self.session._handle_set_level(request)

        # Assert
        assert isinstance(result, EmptyResult)  # Request still succeeds

        # Verify the callback was called (and failed)
        failing_callback.assert_awaited_once_with("info")

        # Verify the level was still set despite callback failure
        assert self.session.logging.current_level == "info"

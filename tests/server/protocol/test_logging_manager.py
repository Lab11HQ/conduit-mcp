import asyncio
from unittest.mock import AsyncMock

from conduit.protocol.common import EmptyResult
from conduit.protocol.logging import SetLevelRequest
from conduit.server.client_manager import ClientManager
from conduit.server.protocol.logging import LoggingManager


class TestLoggingManager:
    def setup_method(self):
        # Arrange - Create client manager and register a test client
        self.client_manager = ClientManager()
        self.client_id = "test-client-123"
        self.client_state = self.client_manager.register_client(self.client_id)

    async def test_handle_set_level_updates_client_level(self):
        # Arrange
        manager = LoggingManager(self.client_manager)
        request = SetLevelRequest(level="info")

        # Verify initial state
        assert self.client_state.log_level is None

        # Act
        result = await manager.handle_set_level(self.client_id, request)

        # Assert
        assert self.client_state.log_level == "info"
        assert isinstance(result, EmptyResult)

    async def test_handle_set_level_calls_callback_if_registered(self):
        # Arrange
        manager = LoggingManager(self.client_manager)
        callback = AsyncMock()
        manager.on_level_change(callback)
        request = SetLevelRequest(level="warning")

        # Act
        await manager.handle_set_level(self.client_id, request)

        # Assert
        await asyncio.sleep(0)  # Yield to let the callback run
        callback.assert_awaited_once_with(self.client_id, "warning")

    async def test_handle_set_level_silent_if_no_callback_registered(self):
        # Arrange
        manager = LoggingManager(self.client_manager)
        request = SetLevelRequest(level="error")

        # Act & Assert - should complete without raising
        result = await manager.handle_set_level(self.client_id, request)
        assert isinstance(result, EmptyResult)

    async def test_handle_set_level_does_not_raise_on_failing_callback(self):
        # Arrange
        manager = LoggingManager(self.client_manager)
        callback = AsyncMock(side_effect=Exception("Test exception"))
        manager.on_level_change(callback)
        request = SetLevelRequest(level="error")

        # Act & Assert - should complete without raising
        result = await manager.handle_set_level(self.client_id, request)
        assert isinstance(result, EmptyResult)

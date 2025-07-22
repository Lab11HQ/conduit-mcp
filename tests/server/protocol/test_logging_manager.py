from unittest.mock import AsyncMock

from conduit.protocol.base import PROTOCOL_VERSION
from conduit.protocol.common import EmptyResult
from conduit.protocol.initialization import ClientCapabilities, Implementation
from conduit.protocol.logging import LoggingLevel, SetLevelRequest
from conduit.server.client_manager import ClientState
from conduit.server.protocol.logging import LoggingManager
from conduit.server.request_context import RequestContext


class TestLoggingManager:
    """Tests for logging level management."""

    def setup_method(self):
        # Arrange - consistent setup for all tests
        self.manager = LoggingManager()
        self.client_id = "test-client-123"
        self.client_state = ClientState(
            capabilities=ClientCapabilities(),
            info=Implementation(name="test-client", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
            initialized=True,
        )
        mock_client_manager = AsyncMock()
        mock_transport = AsyncMock()
        self.context = RequestContext(
            client_id=self.client_id,
            client_state=self.client_state,
            client_manager=mock_client_manager,
            transport=mock_transport,
        )

    async def test_handle_set_level_stores_client_log_level(self):
        # Arrange
        request = SetLevelRequest(level=LoggingLevel.DEBUG)

        # Act
        result = await self.manager.handle_set_level(self.context, request)

        # Assert
        assert isinstance(result, EmptyResult)
        assert self.manager.get_client_level(self.client_id) == "debug"

    async def test_handle_set_level_calls_handler_when_configured(self):
        # Arrange
        handler = AsyncMock()
        self.manager.level_change_handler = handler
        request = SetLevelRequest(level=LoggingLevel.INFO)

        # Act
        result = await self.manager.handle_set_level(self.context, request)

        # Assert
        assert isinstance(result, EmptyResult)
        handler.assert_awaited_once_with(self.client_id, "info")

    async def test_handle_set_level_succeeds_when_no_handler_configured(self):
        # Arrange
        request = SetLevelRequest(level=LoggingLevel.WARNING)
        # No handler configured (level_change_handler remains None)

        # Act & Assert - should not raise any exception
        result = await self.manager.handle_set_level(self.context, request)

        assert isinstance(result, EmptyResult)
        assert self.manager.get_client_level(self.client_id) == "warning"

    async def test_handle_set_level_continues_on_handler_exception(self):
        # Arrange
        failing_handler = AsyncMock(side_effect=RuntimeError("Handler failed"))
        self.manager.level_change_handler = failing_handler
        request = SetLevelRequest(level=LoggingLevel.ERROR)

        # Act - should not raise the handler exception
        result = await self.manager.handle_set_level(self.context, request)

        # Assert - level still gets stored despite handler failure
        assert isinstance(result, EmptyResult)
        assert self.manager.get_client_level(self.client_id) == "error"
        failing_handler.assert_awaited_once_with(self.client_id, "error")

    def test_get_client_level_returns_none_for_unknown_client(self):
        # Arrange - no level set for unknown client

        # Act
        level = self.manager.get_client_level("unknown-client")

        # Assert
        assert level is None

    def test_set_client_level_stores_level_programmatically(self):
        # Arrange - direct server-side level setting

        # Act
        self.manager.set_client_level(self.client_id, "debug")

        # Assert
        assert self.manager.get_client_level(self.client_id) == "debug"

    def test_cleanup_client_removes_client_log_level(self):
        # Arrange
        self.manager.set_client_level(self.client_id, "info")
        assert self.manager.get_client_level(self.client_id) is not None  # Verify setup

        # Act
        self.manager.cleanup_client(self.client_id)

        # Assert
        assert self.manager.get_client_level(self.client_id) is None

    def test_cleanup_client_silently_succeeds_for_unknown_client(self):
        # Arrange - no client exists

        # Act & Assert - should not raise any exception
        self.manager.cleanup_client("unknown-client")

    async def test_handle_set_level_updates_existing_client_level(self):
        # Arrange - client already has a level
        self.manager.set_client_level(self.client_id, "error")
        request = SetLevelRequest(level=LoggingLevel.DEBUG)

        # Act
        result = await self.manager.handle_set_level(self.context, request)

        # Assert - level gets updated
        assert isinstance(result, EmptyResult)
        assert self.manager.get_client_level(self.client_id) == "debug"

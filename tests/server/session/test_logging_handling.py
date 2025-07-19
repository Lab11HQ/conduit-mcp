import asyncio
from unittest.mock import AsyncMock, Mock

from conduit.protocol.base import METHOD_NOT_FOUND, PROTOCOL_VERSION, Error
from conduit.protocol.common import EmptyResult
from conduit.protocol.initialization import Implementation, ServerCapabilities
from conduit.protocol.logging import SetLevelRequest
from conduit.server.session import ServerConfig, ServerSession


class TestLoggingHandling:
    """Test server session logging handling."""

    def setup_method(self):
        self.transport = Mock()
        self.config_with_logging = ServerConfig(
            capabilities=ServerCapabilities(logging=True),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )
        self.config_without_logging = ServerConfig(
            capabilities=ServerCapabilities(),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )
        self.set_level_request = SetLevelRequest(level="info")

    async def test_returns_empty_result_when_capability_enabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_logging)
        client_id = "test-client"

        # Mock the logging manager
        session.logging.handle_set_level = AsyncMock(return_value=EmptyResult())

        # Act
        result = await session._handle_set_level(client_id, self.set_level_request)

        # Assert
        assert result == EmptyResult()
        session.logging.handle_set_level.assert_awaited_once_with(
            client_id, self.set_level_request
        )

    async def test_returns_error_when_capability_disabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_without_logging)
        client_id = "test-client"

        # Act
        result = await session._handle_set_level(client_id, self.set_level_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_callback_failures_do_not_propagate(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_logging)
        client_id = "test-client"

        # Mock the logging manager
        failing_callback = AsyncMock(side_effect=RuntimeError("test error"))
        session.logging.level_change_handler = failing_callback

        # Act
        result = await session._handle_set_level(client_id, self.set_level_request)

        # Assert
        assert result == EmptyResult()
        await asyncio.sleep(0)  # Yield to let the callback run
        failing_callback.assert_awaited_once_with(
            client_id, self.set_level_request.level
        )

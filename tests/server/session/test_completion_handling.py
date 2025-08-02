from unittest.mock import AsyncMock, Mock

from conduit.protocol.base import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    Error,
)
from conduit.protocol.completions import (
    CompleteRequest,
    CompleteResult,
    Completion,
    CompletionArgument,
)
from conduit.protocol.initialization import Implementation, ServerCapabilities
from conduit.protocol.prompts import PromptReference
from conduit.server.client_manager import ClientState
from conduit.server.message_context import MessageContext
from conduit.server.protocol.completions import CompletionNotConfiguredError
from conduit.server.session import ServerConfig, ServerSession


class TestCompletionHandling:
    """Test server session completion handling."""

    def setup_method(self):
        self.transport = Mock()
        self.config_with_completions = ServerConfig(
            capabilities=ServerCapabilities(completions=True),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )
        self.config_without_completions = ServerConfig(
            capabilities=ServerCapabilities(),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )
        self.complete_request = CompleteRequest(
            ref=PromptReference(name="test prompt"),
            argument=CompletionArgument(name="run command", value="py"),
        )
        self.completion = Completion(
            values=["python", "pytest"],
            total=2,
            has_more=False,
        )
        self.context = MessageContext(
            client_id="test-client",
            client_state=ClientState(),
            client_manager=AsyncMock(),
            transport=self.transport,
        )

    async def test_returns_result_when_capability_enabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_completions)

        # Mock the completions manager
        expected_result = CompleteResult(
            completion=self.completion,
        )
        session.completions.handle_complete = AsyncMock(return_value=expected_result)

        # Act
        result = await session._handle_complete(
            self.context,
            self.complete_request,
        )

        # Assert
        assert result == expected_result
        session.completions.handle_complete.assert_awaited_once_with(
            self.context,
            self.complete_request,
        )

    async def test_returns_error_when_capability_disabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_without_completions)

        # Act
        result = await session._handle_complete(self.context, self.complete_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_returns_error_when_no_completion_handler_registered(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_completions)

        # Mock the completions manager
        session.completions.handle_complete = AsyncMock(
            side_effect=CompletionNotConfiguredError
        )

        # Act
        result = await session._handle_complete(self.context, self.complete_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_returns_error_when_handler_raises_exception(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_completions)

        # Mock the completions manager
        session.completions.handle_complete = AsyncMock(
            side_effect=RuntimeError("test error")
        )

        # Act
        result = await session._handle_complete(self.context, self.complete_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR

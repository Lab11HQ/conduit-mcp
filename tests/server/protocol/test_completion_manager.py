from unittest.mock import AsyncMock

import pytest

from conduit.protocol.base import PROTOCOL_VERSION
from conduit.protocol.completions import CompleteRequest, CompleteResult, Completion
from conduit.protocol.initialization import ClientCapabilities, Implementation
from conduit.protocol.prompts import PromptReference
from conduit.server.client_manager import ClientState
from conduit.server.message_context import MessageContext
from conduit.server.protocol.completions import (
    CompletionManager,
    CompletionNotConfiguredError,
)


class TestCompletionManager:
    def setup_method(self):
        self.client_id = "test-client-123"
        self.client_state = ClientState(
            capabilities=ClientCapabilities(),
            info=Implementation(name="test-client", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
            initialized=True,
        )
        mock_client_manager = AsyncMock()
        mock_transport = AsyncMock()
        self.context = MessageContext(
            client_id=self.client_id,
            client_state=self.client_state,
            client_manager=mock_client_manager,
            transport=mock_transport,
        )
        self.manager = CompletionManager()

    async def test_init_creates_unconfigured_manager(self):
        # Arrange
        request = CompleteRequest(
            ref=PromptReference(name="test"),
            argument={"name": "test", "value": "value"},
        )

        # Act & Assert
        with pytest.raises(
            CompletionNotConfiguredError, match="No completion handler registered"
        ):
            await self.manager.handle_complete(self.context, request)

    async def test_handle_complete_calls_handler_and_returns_result(self):
        # Arrange
        request = CompleteRequest(
            ref=PromptReference(name="test"),
            argument={"name": "test", "value": "value"},
        )
        expected_result = CompleteResult(
            completion=Completion(values=["option1", "option2"])
        )
        handler = AsyncMock(return_value=expected_result)

        # Act
        self.manager.completion_handler = handler
        result = await self.manager.handle_complete(self.context, request)

        # Assert
        handler.assert_awaited_once_with(self.context, request)
        assert result is expected_result

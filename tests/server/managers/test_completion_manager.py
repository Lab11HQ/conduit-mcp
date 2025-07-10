from unittest.mock import AsyncMock

import pytest

from conduit.protocol.completions import CompleteRequest, CompleteResult, Completion
from conduit.protocol.prompts import PromptReference
from conduit.server.managers.completions import (
    CompletionManager,
    CompletionNotConfiguredError,
)


class TestCompletionManager:
    async def test_init_creates_unconfigured_manager(self):
        # Arrange
        manager = CompletionManager()
        client_id = "test-client-123"
        request = CompleteRequest(
            ref=PromptReference(name="test"),
            argument={"name": "test", "value": "value"},
        )

        # Act & Assert
        with pytest.raises(
            CompletionNotConfiguredError, match="No completion handler registered"
        ):
            await manager.handle_complete(client_id, request)

    async def test_handle_complete_calls_handler_and_returns_result(self):
        # Arrange
        manager = CompletionManager()
        client_id = "test-client-123"
        request = CompleteRequest(
            ref=PromptReference(name="test"),
            argument={"name": "test", "value": "value"},
        )
        expected_result = CompleteResult(
            completion=Completion(values=["option1", "option2"])
        )
        handler = AsyncMock(return_value=expected_result)

        # Act
        manager.set_handler(handler)
        result = await manager.handle_complete(client_id, request)

        # Assert
        handler.assert_awaited_once_with(client_id, request)
        assert result is expected_result

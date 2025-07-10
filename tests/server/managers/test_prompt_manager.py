from unittest.mock import AsyncMock

import pytest

from conduit.protocol.prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
    Prompt,
)
from conduit.server.managers.prompts import PromptManager


class TestPromptManager:
    def setup_method(self):
        # Arrange - consistent client ID for all tests
        self.client_id = "test-client-123"

    def test_register_stores_prompt_and_handler(self):
        # Arrange
        manager = PromptManager()
        prompt = Prompt(name="test-prompt", description="A test prompt")
        handler = AsyncMock()

        # Act
        manager.register(prompt, handler)

        # Assert
        assert "test-prompt" in manager.registered
        assert manager.registered["test-prompt"] is prompt
        assert "test-prompt" in manager.handlers
        assert manager.handlers["test-prompt"] is handler

    async def test_handle_list_prompts_returns_empty_list_when_no_prompts(self):
        # Arrange
        manager = PromptManager()
        request = ListPromptsRequest()

        # Act
        result = await manager.handle_list_prompts(self.client_id, request)

        # Assert
        assert result == ListPromptsResult(prompts=[])

    async def test_handle_list_prompts_returns_registered_prompts(self):
        # Arrange
        manager = PromptManager()
        prompt1 = Prompt(name="prompt1", description="First prompt")
        prompt2 = Prompt(name="prompt2", description="Second prompt")
        handler = AsyncMock()

        manager.register(prompt1, handler)
        manager.register(prompt2, handler)
        request = ListPromptsRequest()

        # Act
        result = await manager.handle_list_prompts(self.client_id, request)

        # Assert
        assert isinstance(result, ListPromptsResult)
        assert len(result.prompts) == 2
        assert prompt1 in result.prompts
        assert prompt2 in result.prompts

    async def test_handle_get_prompt_calls_handler_and_returns_result(self):
        # Arrange
        manager = PromptManager()
        prompt = Prompt(name="test-prompt", description="A test prompt")
        expected_result = GetPromptResult(description="Test result", messages=[])
        handler = AsyncMock(return_value=expected_result)

        manager.register(prompt, handler)
        request = GetPromptRequest(name="test-prompt")

        # Act
        result = await manager.handle_get_prompt(self.client_id, request)

        # Assert
        handler.assert_awaited_once_with(self.client_id, request)
        assert result is expected_result

    async def test_handle_get_prompt_raises_keyerror_for_unknown_prompt(self):
        # Arrange
        manager = PromptManager()
        request = GetPromptRequest(name="unknown-prompt-name")

        # Act & Assert
        with pytest.raises(KeyError, match="Unknown prompt: unknown-prompt-name"):
            await manager.handle_get_prompt(self.client_id, request)

from unittest.mock import AsyncMock

import pytest

from conduit.protocol.base import PROTOCOL_VERSION
from conduit.protocol.initialization import ClientCapabilities, Implementation
from conduit.protocol.prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
    Prompt,
)
from conduit.server.client_manager import ClientState
from conduit.server.message_context import MessageContext
from conduit.server.protocol.prompts import PromptManager


class TestGlobalPromptManagement:
    def setup_method(self):
        # Arrange - consistent setup for all tests
        self.manager = PromptManager()
        self.client_id = "test_client"
        self.prompt = Prompt(name="test_prompt", description="Test prompt")
        self.handler = AsyncMock(return_value=GetPromptResult(messages=[]))

    def test_add_prompt_stores_prompt_and_handler(self):
        # Arrange - setup already done in setup_method

        # Act - add the prompt with its handler
        self.manager.add_prompt(self.prompt, self.handler)

        # Assert - verify prompt and handler are stored correctly
        assert "test_prompt" in self.manager.global_prompts
        assert self.manager.global_prompts["test_prompt"] == self.prompt
        assert "test_prompt" in self.manager.global_handlers
        assert self.manager.global_handlers["test_prompt"] == self.handler

    def test_get_prompts_returns_all_global_prompts(self):
        # Arrange - add multiple prompts
        prompt1 = Prompt(name="prompt1", description="First prompt")
        prompt2 = Prompt(name="prompt2", description="Second prompt")
        handler1 = AsyncMock(return_value=GetPromptResult(messages=[]))
        handler2 = AsyncMock(return_value=GetPromptResult(messages=[]))

        self.manager.add_prompt(prompt1, handler1)
        self.manager.add_prompt(prompt2, handler2)

        # Act - get all prompts
        result = self.manager.get_prompts()

        # Assert - verify all prompts are returned and it's a copy
        assert len(result) == 2
        assert result["prompt1"] == prompt1
        assert result["prompt2"] == prompt2
        assert result is not self.manager.global_prompts  # defensive copy

    def test_get_prompt_returns_specific_prompt(self):
        # Arrange - add the prompt
        self.manager.add_prompt(self.prompt, self.handler)

        # Act - get specific prompt
        result = self.manager.get_prompt("test_prompt")

        # Assert - verify correct prompt is returned
        assert result == self.prompt

    def test_get_prompt_returns_none_for_unknown_prompt(self):
        # Arrange - no prompts added

        # Act - try to get non-existent prompt
        result = self.manager.get_prompt("unknown_prompt")

        # Assert - verify None is returned
        assert result is None

    def test_remove_prompt_removes_prompt_and_handler(self):
        # Arrange - add the prompt
        self.manager.add_prompt(self.prompt, self.handler)
        assert "test_prompt" in self.manager.global_prompts
        assert "test_prompt" in self.manager.global_handlers

        # Act - remove the prompt
        self.manager.remove_prompt("test_prompt")

        # Assert - verify prompt and handler are removed
        assert "test_prompt" not in self.manager.global_prompts
        assert "test_prompt" not in self.manager.global_handlers

    def test_remove_prompt_silently_succeeds_for_unknown_prompt(self):
        # Arrange - no prompts added

        # Act - remove non-existent prompt (should not raise)
        self.manager.remove_prompt("unknown_prompt")

        # Assert - verify no error occurred and state unchanged
        assert len(self.manager.global_prompts) == 0
        assert len(self.manager.global_handlers) == 0

    def test_clear_prompts_removes_all_prompts_and_handlers(self):
        # Arrange - add multiple prompts
        prompt1 = Prompt(name="prompt1", description="First prompt")
        prompt2 = Prompt(name="prompt2", description="Second prompt")
        handler1 = AsyncMock(return_value=GetPromptResult(messages=[]))
        handler2 = AsyncMock(return_value=GetPromptResult(messages=[]))

        self.manager.add_prompt(prompt1, handler1)
        self.manager.add_prompt(prompt2, handler2)
        assert len(self.manager.global_prompts) == 2
        assert len(self.manager.global_handlers) == 2

        # Act - clear all prompts
        self.manager.clear_prompts()

        # Assert - verify all prompts and handlers are removed
        assert len(self.manager.global_prompts) == 0
        assert len(self.manager.global_handlers) == 0

    def test_clear_prompts_on_empty_manager_succeeds(self):
        # Arrange - no prompts added

        # Act - clear prompts (should not raise)
        self.manager.clear_prompts()

        # Assert - verify no error occurred and state unchanged
        assert len(self.manager.global_prompts) == 0
        assert len(self.manager.global_handlers) == 0


class TestClientPromptManagement:
    def setup_method(self):
        # Arrange - consistent setup for all tests
        self.manager = PromptManager()
        self.client_id = "test_client"
        self.global_prompt = Prompt(name="global_prompt", description="Global prompt")
        self.global_handler = AsyncMock(return_value=GetPromptResult(messages=[]))
        self.client_prompt = Prompt(name="client_prompt", description="Client prompt")
        self.client_handler = AsyncMock(return_value=GetPromptResult(messages=[]))

    def test_add_client_prompt_stores_prompt_and_handler(self):
        # Arrange - setup already done in setup_method

        # Act - add client-specific prompt
        self.manager.add_client_prompt(
            self.client_id, self.client_prompt, self.client_handler
        )

        # Assert - verify prompt and handler are stored for the client
        assert self.client_id in self.manager.client_prompts
        assert "client_prompt" in self.manager.client_prompts[self.client_id]
        assert (
            self.manager.client_prompts[self.client_id]["client_prompt"]
            == self.client_prompt
        )
        assert self.client_id in self.manager.client_handlers
        assert "client_prompt" in self.manager.client_handlers[self.client_id]
        assert (
            self.manager.client_handlers[self.client_id]["client_prompt"]
            == self.client_handler
        )

    def test_get_client_prompts_combines_global_and_client_prompts(self):
        # Arrange - add global prompt and different client-specific prompt

        self.manager.add_prompt(self.global_prompt, self.global_handler)
        self.manager.add_client_prompt(
            self.client_id, self.client_prompt, self.client_handler
        )

        # Act - get prompts for client
        result = self.manager.get_client_prompts(self.client_id)

        # Assert - verify both global and client prompts are returned
        assert len(result) == 2
        assert result["global_prompt"] == self.global_prompt
        assert result["client_prompt"] == self.client_prompt

    def test_get_client_prompts_client_overrides_global(self):
        # Arrange - add both global and client-specific prompts with same name
        global_prompt = Prompt(name="generic_prompt", description="Global prompt")
        global_handler = AsyncMock(return_value=GetPromptResult(messages=[]))
        client_prompt = Prompt(name="generic_prompt", description="Client prompt")
        client_handler = AsyncMock(return_value=GetPromptResult(messages=[]))

        self.manager.add_prompt(global_prompt, global_handler)
        self.manager.add_client_prompt(self.client_id, client_prompt, client_handler)

        # Act - get prompts for client
        result = self.manager.get_client_prompts(self.client_id)

        # Assert - verify client-specific prompt overrides global
        assert len(result) == 1
        assert result["generic_prompt"] == client_prompt
        assert result["generic_prompt"] is not global_prompt

    def test_remove_client_prompt_removes_prompt_and_handler(self):
        # Arrange - add client-specific prompt
        self.manager.add_client_prompt(
            self.client_id, self.client_prompt, self.client_handler
        )
        assert "client_prompt" in self.manager.client_prompts[self.client_id]
        assert "client_prompt" in self.manager.client_handlers[self.client_id]

        # Act - remove the client-specific prompt
        self.manager.remove_client_prompt(self.client_id, "client_prompt")

        # Assert - verify prompt and handler are removed
        assert "client_prompt" not in self.manager.client_prompts[self.client_id]
        assert "client_prompt" not in self.manager.client_handlers[self.client_id]

    def test_remove_client_prompt_silently_succeeds_for_unknown_client(self):
        # Arrange - no client prompts added

        # Act - remove prompt from non-existent client (should not raise)
        self.manager.remove_client_prompt("unknown_client", "some_prompt")

        # Assert - verify no error occurred and state unchanged
        assert len(self.manager.client_prompts) == 0
        assert len(self.manager.client_handlers) == 0

    def test_remove_client_prompt_silently_succeeds_for_unknown_prompt(self):
        # Arrange - add client but different prompt
        self.manager.add_client_prompt(
            self.client_id, self.client_prompt, self.client_handler
        )

        # Act - remove non-existent prompt (should not raise)
        self.manager.remove_client_prompt(self.client_id, "unknown_prompt")

        # Assert - verify no error occurred and existing prompt unchanged
        assert "client_prompt" in self.manager.client_prompts[self.client_id]
        assert "client_prompt" in self.manager.client_handlers[self.client_id]

    def test_cleanup_client_removes_all_client_data(self):
        # Arrange - add multiple prompts for client
        prompt1 = Prompt(name="prompt1", description="First prompt")
        prompt2 = Prompt(name="prompt2", description="Second prompt")
        handler1 = AsyncMock(return_value=GetPromptResult(messages=[]))
        handler2 = AsyncMock(return_value=GetPromptResult(messages=[]))

        self.manager.add_client_prompt(self.client_id, prompt1, handler1)
        self.manager.add_client_prompt(self.client_id, prompt2, handler2)
        assert self.client_id in self.manager.client_prompts
        assert self.client_id in self.manager.client_handlers
        assert len(self.manager.client_prompts[self.client_id]) == 2

        # Act - cleanup the client
        self.manager.cleanup_client(self.client_id)

        # Assert - verify all client data is removed
        assert self.client_id not in self.manager.client_prompts
        assert self.client_id not in self.manager.client_handlers

    def test_cleanup_client_silently_succeeds_for_unknown_client(self):
        # Arrange - add a global prompt and a client-specific prompt
        self.manager.add_prompt(self.global_prompt, self.global_handler)
        self.manager.add_client_prompt(
            self.client_id, self.client_prompt, self.client_handler
        )

        # Act - cleanup non-existent client (should not raise)
        self.manager.cleanup_client("unknown_client")

        # Assert - verify no error occurred and state unchanged
        assert len(self.manager.client_prompts) == 1
        assert len(self.manager.global_prompts) == 1


class TestProtocolHandlers:
    def setup_method(self):
        # Arrange - consistent setup for all tests
        self.manager = PromptManager()
        self.client_id = "test_client"
        self.global_prompt = Prompt(name="global_prompt", description="Global prompt")
        self.global_handler = AsyncMock(return_value=GetPromptResult(messages=[]))
        self.client_prompt = Prompt(name="client_prompt", description="Client prompt")
        self.client_handler = AsyncMock(return_value=GetPromptResult(messages=[]))

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

    async def test_handle_list_prompts_returns_client_available_prompts(self):
        # Arrange - add both global and client-specific prompts
        self.manager.add_prompt(self.global_prompt, self.global_handler)
        self.manager.add_client_prompt(
            self.client_id, self.client_prompt, self.client_handler
        )
        request = ListPromptsRequest()

        # Act - handle list prompts request
        result = await self.manager.handle_list_prompts(self.context, request)

        # Assert - verify all available prompts are returned for this client
        assert isinstance(result, ListPromptsResult)
        assert len(result.prompts) == 2
        prompt_names = {prompt.name for prompt in result.prompts}
        assert "global_prompt" in prompt_names
        assert "client_prompt" in prompt_names

    async def test_handle_get_prompt_uses_global_handler(self):
        # Arrange - add global prompt and create request
        self.manager.add_prompt(self.global_prompt, self.global_handler)
        request = GetPromptRequest(name="global_prompt", arguments={})

        # Act - handle get prompt request
        result = await self.manager.handle_get_prompt(self.context, request)

        # Assert - verify global handler was called and result returned
        self.global_handler.assert_awaited_once_with(self.context, request)
        assert result == self.global_handler.return_value

    async def test_handle_get_prompt_uses_client_handler(self):
        # Arrange - add client-specific prompt and create request
        self.manager.add_client_prompt(
            self.client_id, self.client_prompt, self.client_handler
        )
        request = GetPromptRequest(name="client_prompt", arguments={})

        # Act - handle get prompt request
        result = await self.manager.handle_get_prompt(self.context, request)

        # Assert - verify client handler was called and result returned
        self.client_handler.assert_awaited_once_with(self.context, request)
        assert result == self.client_handler.return_value

    async def test_handle_get_prompt_client_handler_overrides_global(self):
        # Arrange - add both global and client handlers for same prompt name
        override_prompt = Prompt(name="override_prompt", description="Override prompt")
        global_handler = AsyncMock(return_value=GetPromptResult(messages=[]))
        client_handler = AsyncMock(return_value=GetPromptResult(messages=[]))

        self.manager.add_prompt(override_prompt, global_handler)
        self.manager.add_client_prompt(self.client_id, override_prompt, client_handler)
        request = GetPromptRequest(name="override_prompt", arguments={})

        # Act - handle get prompt request
        result = await self.manager.handle_get_prompt(self.context, request)

        # Assert - verify client handler was used, not global
        client_handler.assert_awaited_once_with(self.context, request)
        global_handler.assert_not_awaited()
        assert result == client_handler.return_value

    async def test_handle_get_prompt_raises_keyerror_for_unknown_prompt(self):
        # Arrange - no prompts added
        request = GetPromptRequest(name="unknown_prompt", arguments={})

        # Act & Assert - verify KeyError is raised for unknown prompt
        with pytest.raises(KeyError, match="Prompt 'unknown_prompt' not found"):
            await self.manager.handle_get_prompt(self.context, request)

    async def test_handle_get_prompt_reraises_handler_exceptions(self):
        # Arrange - add prompt with handler that raises exception
        failing_handler = AsyncMock(side_effect=ValueError("Handler failed"))
        self.manager.add_prompt(self.global_prompt, failing_handler)
        request = GetPromptRequest(name="global_prompt", arguments={})

        # Act & Assert - verify handler exception is re-raised
        with pytest.raises(ValueError):
            await self.manager.handle_get_prompt(self.context, request)

        # Assert - verify handler was called before failing
        failing_handler.assert_awaited_once_with(self.context, request)

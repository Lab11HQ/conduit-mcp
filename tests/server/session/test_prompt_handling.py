from unittest.mock import AsyncMock

from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND, Error
from conduit.protocol.content import TextContent
from conduit.protocol.initialization import PromptsCapability
from conduit.protocol.prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
    Prompt,
    PromptMessage,
)

from .conftest import ServerSessionTest


class TestListPrompts(ServerSessionTest):
    async def test_returns_prompts_from_manager_when_capability_enabled(self):
        """Test successful prompt listing when prompts capability is enabled."""
        # Arrange
        self.config.capabilities.prompts = PromptsCapability()

        # Create expected prompts
        prompt1 = Prompt(
            name="test_prompt_1",
            description="A test prompt",
        )
        prompt2 = Prompt(
            name="test_prompt_2",
            description="Another test prompt",
        )

        # Mock the manager to return our prompts
        self.session.prompts.handle_list_prompts = AsyncMock(
            return_value=ListPromptsResult(prompts=[prompt1, prompt2])
        )

        request = ListPromptsRequest()

        # Act
        result = await self.session._handle_list_prompts(request)

        # Assert
        assert isinstance(result, ListPromptsResult)
        assert len(result.prompts) == 2
        assert result.prompts[0].name == "test_prompt_1"
        assert result.prompts[1].name == "test_prompt_2"

        # Verify manager was called
        self.session.prompts.handle_list_prompts.assert_awaited_once_with(request)

    async def test_rejects_list_prompts_when_capability_not_set(self):
        """Test error when prompts capability is not configured."""
        # Arrange
        self.config.capabilities.prompts = None  # No prompts capability
        request = ListPromptsRequest()

        # Act
        result = await self.session._handle_list_prompts(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support prompts capability"


class TestGetPrompt(ServerSessionTest):
    async def test_returns_result_from_manager_when_capability_enabled(self):
        """Test successful prompt retrieval when prompts capability is enabled."""
        # Arrange
        self.config.capabilities.prompts = PromptsCapability()

        expected_result = GetPromptResult(
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(text="Test prompt content"),
                )
            ]
        )

        # Mock the manager to return success
        self.session.prompts.handle_get_prompt = AsyncMock(return_value=expected_result)

        request = GetPromptRequest(name="test_prompt", arguments={"arg1": "value1"})

        # Act
        result = await self.session._handle_get_prompt(request)

        # Assert
        assert isinstance(result, GetPromptResult)
        assert len(result.messages) == 1
        assert result.messages[0].content.text == "Test prompt content"

        # Verify manager was called
        self.session.prompts.handle_get_prompt.assert_awaited_once_with(request)

    async def test_rejects_get_prompt_when_capability_not_set(self):
        """Test error when prompts capability is not configured."""
        # Arrange
        self.config.capabilities.prompts = None  # No prompts capability
        request = GetPromptRequest(name="test_prompt", arguments={"arg1": "value1"})

        # Act
        result = await self.session._handle_get_prompt(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support prompts capability"

    async def test_returns_method_not_found_when_prompt_unknown(self):
        """Test error when manager raises KeyError for unknown prompt."""
        # Arrange
        self.config.capabilities.prompts = PromptsCapability()

        # Mock the manager to raise KeyError (unknown prompt)
        self.session.prompts.handle_get_prompt = AsyncMock(
            side_effect=KeyError("Unknown prompt: unknown_prompt")
        )

        request = GetPromptRequest(name="unknown_prompt", arguments={"arg1": "value1"})

        # Act
        result = await self.session._handle_get_prompt(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "unknown_prompt" in result.message

        # Verify manager was called
        self.session.prompts.handle_get_prompt.assert_awaited_once_with(request)

    async def test_returns_internal_error_when_manager_raises_exception(self):
        """Test error when manager raises unexpected exception."""
        # Arrange
        self.config.capabilities.prompts = PromptsCapability()

        # Mock the manager to raise generic exception
        self.session.prompts.handle_get_prompt = AsyncMock(
            side_effect=ValueError("Something went wrong")
        )

        request = GetPromptRequest(name="test_prompt", arguments={"arg1": "value1"})

        # Act
        result = await self.session._handle_get_prompt(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert result.message == "Error in prompt handler"

        # Verify manager was called
        self.session.prompts.handle_get_prompt.assert_awaited_once_with(request)

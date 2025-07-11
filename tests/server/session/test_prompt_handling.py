from unittest.mock import AsyncMock, Mock

from conduit.protocol.base import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    Error,
)
from conduit.protocol.content import TextContent
from conduit.protocol.initialization import (
    Implementation,
    PromptsCapability,
    ServerCapabilities,
)
from conduit.protocol.prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
    PromptMessage,
)
from conduit.server.session_v2 import ServerConfig, ServerSession


class TestPromptHandling:
    """Test server session prompt handling."""

    def setup_method(self):
        self.transport = Mock()
        self.config_with_prompts = ServerConfig(
            capabilities=ServerCapabilities(prompts=PromptsCapability()),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )
        self.config_without_prompts = ServerConfig(
            capabilities=ServerCapabilities(),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )

    async def test_list_prompts_returns_result_when_capability_enabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_prompts)
        client_id = "test-client"

        # Mock the prompts manager
        expected_result = ListPromptsResult(prompts=[])
        session.prompts.handle_list_prompts = AsyncMock(return_value=expected_result)

        # Act
        result = await session._handle_list_prompts(client_id, ListPromptsRequest())

        # Assert
        assert result == expected_result
        session.prompts.handle_list_prompts.assert_awaited_once_with(
            client_id, ListPromptsRequest()
        )

    async def test_list_prompts_returns_error_when_capability_disabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_without_prompts)
        client_id = "test-client"

        # Act
        result = await session._handle_list_prompts(client_id, ListPromptsRequest())

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_get_prompt_returns_result_when_capability_enabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_prompts)
        client_id = "test-client"

        # Mock the prompts manager
        expected_result = GetPromptResult(
            description="Test Description",
            messages=[
                PromptMessage(role="user", content=TextContent(text="Test Content"))
            ],
        )
        session.prompts.handle_get_prompt = AsyncMock(return_value=expected_result)

        # Act
        result = await session._handle_get_prompt(
            client_id, GetPromptRequest(name="test-prompt")
        )

        # Assert
        assert result == expected_result
        session.prompts.handle_get_prompt.assert_awaited_once_with(
            client_id, GetPromptRequest(name="test-prompt")
        )

    async def test_get_prompt_returns_error_when_capability_disabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_without_prompts)
        client_id = "test-client"

        # Act
        result = await session._handle_get_prompt(
            client_id, GetPromptRequest(name="test-prompt")
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

    async def test_get_prompt_returns_error_when_prompt_not_found(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_prompts)
        client_id = "test-client"

        # Mock the prompts manager
        session.prompts.handle_get_prompt = AsyncMock(
            side_effect=KeyError("test-prompt")
        )

        # Act
        result = await session._handle_get_prompt(
            client_id, GetPromptRequest(name="test-prompt")
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

        # Verify manager was called
        session.prompts.handle_get_prompt.assert_awaited_once_with(
            client_id, GetPromptRequest(name="test-prompt")
        )

    async def test_returns_error_when_handler_raises_generic_exception(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_prompts)
        client_id = "test-client"

        # Mock the prompts manager
        session.prompts.handle_get_prompt = AsyncMock(
            side_effect=RuntimeError("test-error")
        )

        # Act
        result = await session._handle_get_prompt(
            client_id, GetPromptRequest(name="test-prompt")
        )

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR

        # Verify manager was called
        session.prompts.handle_get_prompt.assert_awaited_once_with(
            client_id, GetPromptRequest(name="test-prompt")
        )

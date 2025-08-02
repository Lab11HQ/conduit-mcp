from unittest.mock import AsyncMock

import pytest

from conduit.client.message_context import MessageContext
from conduit.client.protocol.sampling import SamplingManager, SamplingNotConfiguredError
from conduit.protocol.content import TextContent
from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult


class TestSamplingManager:
    def setup_method(self):
        self.context = MessageContext(
            server_id="server_id",
            server_state=AsyncMock(),
            server_manager=AsyncMock(),
            transport=AsyncMock(),
        )

    async def test_init_creates_unconfigured_manager(self):
        # Arrange
        manager = SamplingManager()
        request = CreateMessageRequest(
            messages=[],
            max_tokens=100,
        )

        # Act & Assert
        with pytest.raises(
            SamplingNotConfiguredError, match="No sampling handler registered"
        ):
            await manager.handle_create_message(self.context, request)

    async def test_handle_create_message_calls_handler_and_returns_result(self):
        # Arrange
        manager = SamplingManager()
        request = CreateMessageRequest(
            messages=[],
            max_tokens=100,
        )
        expected_result = CreateMessageResult(
            role="assistant",
            content=TextContent(text="Hello!"),
            model="gpt-4o",
        )
        handler = AsyncMock(return_value=expected_result)

        # Act
        manager.sampling_handler = handler
        result = await manager.handle_create_message(self.context, request)

        # Assert
        handler.assert_awaited_once_with(request)
        assert result is expected_result

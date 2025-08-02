from unittest.mock import AsyncMock

import pytest

from conduit.client.message_context import MessageContext
from conduit.client.protocol.elicitation import (
    ElicitationManager,
    ElicitationNotConfiguredError,
)
from conduit.protocol.elicitation import (
    ElicitRequest,
    ElicitResult,
    NumberSchema,
    RequestedSchema,
)


class TestElicitationManager:
    def setup_method(self):
        self.context = MessageContext(
            server_id="server_id",
            server_state=AsyncMock(),
            server_manager=AsyncMock(),
            transport=AsyncMock(),
        )

    async def test_init_creates_unconfigured_manager(self):
        # Arrange
        manager = ElicitationManager()
        request = ElicitRequest(
            message="Riddle me this:",
            requested_schema=RequestedSchema(
                type="object",
                properties={"number": NumberSchema(type="number")},
            ),
        )

        # Act & Assert
        with pytest.raises(ElicitationNotConfiguredError):
            await manager.handle_elicitation(self.context, request)

    async def test_handle_elicitation_calls_handler_and_returns_result(self):
        # Arrange
        manager = ElicitationManager()
        request = ElicitRequest(
            message="Riddle me this:",
            requested_schema=RequestedSchema(
                type="object",
                properties={"number": NumberSchema(type="number")},
            ),
        )
        expected_result = ElicitResult(action="accept", content={"number": 11})
        handler = AsyncMock(return_value=expected_result)

        # Act
        manager.elicitation_handler = handler
        result = await manager.handle_elicitation(self.context, request)

        # Assert
        handler.assert_awaited_once_with(request)
        assert result is expected_result

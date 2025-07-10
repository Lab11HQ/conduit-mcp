from unittest.mock import AsyncMock

import pytest

from conduit.protocol.content import TextContent
from conduit.protocol.tools import (
    CallToolRequest,
    CallToolResult,
    JSONSchema,
    ListToolsRequest,
    ListToolsResult,
    Tool,
)
from conduit.server.managers.tools import ToolManager


class TestToolManager:
    def setup_method(self):
        # Arrange - consistent client ID for all tests
        self.client_id = "test-client-123"

    def test_register_stores_tool_and_handler(self):
        # Arrange
        manager = ToolManager()
        tool = Tool(
            name="test-tool", description="A test tool", input_schema=JSONSchema()
        )
        handler = AsyncMock()

        # Act
        manager.register(tool, handler)

        # Assert
        assert "test-tool" in manager.registered
        assert manager.registered["test-tool"] is tool
        assert "test-tool" in manager.handlers
        assert manager.handlers["test-tool"] is handler

    async def test_handle_list_returns_registered_tools(self):
        # Arrange
        manager = ToolManager()
        tool = Tool(
            name="test-tool", description="A test tool", input_schema=JSONSchema()
        )
        handler = AsyncMock()
        manager.register(tool, handler)
        request = ListToolsRequest()

        # Act
        result = await manager.handle_list(self.client_id, request)

        # Assert
        assert isinstance(result, ListToolsResult)
        assert result.tools == [tool]

    async def test_handle_call_delegates_to_handler_and_returns_result(self):
        # Arrange
        manager = ToolManager()
        tool = Tool(
            name="test-tool", description="A test tool", input_schema=JSONSchema()
        )
        expected_result = CallToolResult(content=[TextContent(text="success")])
        handler = AsyncMock(return_value=expected_result)
        manager.register(tool, handler)
        request = CallToolRequest(name="test-tool", arguments={})

        # Act
        result = await manager.handle_call(self.client_id, request)

        # Assert
        handler.assert_awaited_once_with(self.client_id, request)
        assert result is expected_result

    async def test_handle_call_raises_keyerror_for_unknown_tool(self):
        # Arrange
        manager = ToolManager()
        request = CallToolRequest(name="unknown-tool", arguments={})

        # Act & Assert
        with pytest.raises(KeyError):
            await manager.handle_call(self.client_id, request)

    async def test_handle_call_converts_handler_exception_to_error_result(self):
        # Arrange
        manager = ToolManager()
        tool = Tool(
            name="failing-tool", description="A failing tool", input_schema=JSONSchema()
        )
        handler = AsyncMock(side_effect=RuntimeError("Something went wrong"))
        manager.register(tool, handler)
        request = CallToolRequest(name="failing-tool", arguments={})

        # Act
        result = await manager.handle_call(self.client_id, request)

        # Assert
        assert isinstance(result, CallToolResult)
        assert result.is_error is True
        assert len(result.content) == 1

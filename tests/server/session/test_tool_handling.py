from unittest.mock import AsyncMock

from conduit.protocol.base import METHOD_NOT_FOUND, Error
from conduit.protocol.content import TextContent
from conduit.protocol.initialization import ToolsCapability
from conduit.protocol.tools import (
    CallToolRequest,
    CallToolResult,
    JSONSchema,
    ListToolsRequest,
    ListToolsResult,
    Tool,
)

from .conftest import ServerSessionTest


class TestListTools(ServerSessionTest):
    async def test_returns_tools_from_manager_when_capability_enabled(self):
        """Test successful tool listing when tools capability is enabled."""
        # Arrange
        self.config.capabilities.tools = ToolsCapability()

        # Create expected tools
        tool1 = Tool(
            name="test_tool_1",
            description="A test tool",
            input_schema=JSONSchema(properties={"arg1": {"type": "string"}}),
        )
        tool2 = Tool(
            name="test_tool_2",
            description="Another test tool",
            input_schema=JSONSchema(properties={"arg2": {"type": "number"}}),
        )

        # Mock the manager to return our tools
        self.session.tools.handle_list = AsyncMock(
            return_value=ListToolsResult(tools=[tool1, tool2])
        )

        request = ListToolsRequest()

        # Act
        result = await self.session._handle_list_tools(request)

        # Assert
        assert isinstance(result, ListToolsResult)
        assert len(result.tools) == 2
        assert result.tools[0].name == "test_tool_1"
        assert result.tools[1].name == "test_tool_2"

        # Verify manager was called
        self.session.tools.handle_list.assert_awaited_once_with(request)

    async def test_rejects_list_tools_when_capability_not_set(self):
        """Test error when tools capability is not configured."""
        # Arrange
        self.config.capabilities.tools = None  # No tools capability
        request = ListToolsRequest()

        # Act
        result = await self.session._handle_list_tools(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support tools capability"


class TestCallTool(ServerSessionTest):
    async def test_returns_result_from_manager_when_capability_enabled(self):
        """Test successful tool call when tools capability is enabled."""
        # Arrange
        self.config.capabilities.tools = ToolsCapability()

        expected_result = CallToolResult(
            content=[TextContent(text="Tool executed successfully")],
            is_error=False,
        )

        # Mock the manager to return success
        self.session.tools.handle_call = AsyncMock(return_value=expected_result)

        request = CallToolRequest(name="test_tool", arguments={"arg1": "value1"})

        # Act
        result = await self.session._handle_call_tool(request)

        # Assert
        assert isinstance(result, CallToolResult)
        assert result.content[0].text == "Tool executed successfully"
        assert result.is_error is False

        # Verify manager was called
        self.session.tools.handle_call.assert_awaited_once_with(request)

    async def test_rejects_call_tool_when_capability_not_set(self):
        """Test error when tools capability is not configured."""
        # Arrange
        self.config.capabilities.tools = None  # No tools capability
        request = CallToolRequest(name="test_tool", arguments={"arg1": "value1"})

        # Act
        result = await self.session._handle_call_tool(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support tools capability"

    async def test_returns_method_not_found_when_tool_unknown(self):
        """Test error when manager raises KeyError for unknown tool."""
        # Arrange
        self.config.capabilities.tools = ToolsCapability()

        # Mock the manager to raise KeyError (unknown tool)
        self.session.tools.handle_call = AsyncMock(side_effect=KeyError("unknown_tool"))

        request = CallToolRequest(name="unknown_tool", arguments={"arg1": "value1"})

        # Act
        result = await self.session._handle_call_tool(request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Unknown tool: unknown_tool"

        # Verify manager was called
        self.session.tools.handle_call.assert_awaited_once_with(request)

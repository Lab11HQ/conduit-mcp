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
from conduit.server.protocol.tools import ToolManager


class TestGlobalToolManagement:
    """Tests for global tool registration and retrieval."""

    def setup_method(self):
        # Arrange - consistent setup for all tests
        self.manager = ToolManager()
        self.tool = Tool(
            name="calculator",
            description="A calculator tool",
            input_schema=JSONSchema(),
        )
        self.handler = AsyncMock()

    def test_add_tool_stores_global_tool_and_handler(self):
        # Arrange - setup already done in setup_method

        # Act
        self.manager.add_tool(self.tool, self.handler)

        # Assert
        assert "calculator" in self.manager.global_tools
        assert self.manager.global_tools["calculator"] is self.tool
        assert "calculator" in self.manager.global_handlers
        assert self.manager.global_handlers["calculator"] is self.handler

    def test_get_tools_returns_all_global_tools(self):
        # Arrange
        self.manager.add_tool(self.tool, self.handler)

        # Act
        tools = self.manager.get_tools()

        # Assert
        assert len(tools) == 1
        assert "calculator" in tools
        assert tools["calculator"].name == "calculator"
        assert tools["calculator"].description == "A calculator tool"

    def test_get_tool_returns_specific_global_tool(self):
        # Arrange
        self.manager.add_tool(self.tool, self.handler)

        # Act
        result = self.manager.get_tool("calculator")

        # Assert
        assert result is not None
        assert result.name == "calculator"
        assert result.description == "A calculator tool"

    def test_get_tool_returns_none_for_unknown_tool(self):
        # Arrange - empty manager
        assert self.manager.global_tools == {}
        assert self.manager.global_handlers == {}

        # Act
        result = self.manager.get_tool("nonexistent")

        # Assert
        assert result is None

    def test_remove_tool_removes_global_tool_and_handler(self):
        # Arrange
        self.manager.add_tool(self.tool, self.handler)
        assert "calculator" in self.manager.global_tools  # Verify it's there

        # Act
        self.manager.remove_tool("calculator")

        # Assert
        assert "calculator" not in self.manager.global_tools
        assert "calculator" not in self.manager.global_handlers

    def test_remove_tool_silently_succeeds_for_unknown_tool(self):
        # Arrange - empty manager
        assert self.manager.global_tools == {}
        assert self.manager.global_handlers == {}

        # Act & Assert - should not raise any exception
        self.manager.remove_tool("nonexistent")

        # Verify manager state is unchanged
        assert len(self.manager.global_tools) == 0
        assert len(self.manager.global_handlers) == 0

    def test_clear_tools_removes_all_global_tools_and_handlers(self):
        # Arrange - add multiple tools
        tool2 = Tool(
            name="weather", description="A weather tool", input_schema=JSONSchema()
        )
        handler2 = AsyncMock()

        self.manager.add_tool(self.tool, self.handler)
        self.manager.add_tool(tool2, handler2)
        assert len(self.manager.global_tools) == 2  # Verify setup

        # Act
        self.manager.clear_tools()

        # Assert
        assert len(self.manager.global_tools) == 0
        assert len(self.manager.global_handlers) == 0

    def test_clear_tools_on_empty_manager_succeeds(self):
        # Arrange - empty manager
        assert self.manager.global_tools == {}
        assert self.manager.global_handlers == {}

        # Act & Assert - should not raise any exception
        self.manager.clear_tools()

        # Verify manager is still empty
        assert len(self.manager.global_tools) == 0
        assert len(self.manager.global_handlers) == 0


class TestClientToolManagement:
    """Tests for client-specific tool registration and retrieval."""

    def setup_method(self):
        # Arrange - consistent setup for all tests
        self.manager = ToolManager()
        self.client_id = "test-client-123"
        self.client_tool = Tool(
            name="Client-specific tool",
            description="Access client-specific tool",
            input_schema=JSONSchema(),
        )
        self.global_tool = Tool(
            name="Global tool",
            description="Access global tool",
            input_schema=JSONSchema(),
        )
        self.handler = AsyncMock()

    def test_add_client_tool_stores_client_specific_tool_and_handler(self):
        # Arrange - setup already done in setup_method

        # Act
        self.manager.add_client_tool(self.client_id, self.client_tool, self.handler)

        # Assert
        assert self.client_id in self.manager.client_tools
        assert "Client-specific tool" in self.manager.client_tools[self.client_id]
        assert (
            self.manager.client_tools[self.client_id]["Client-specific tool"]
            is self.client_tool
        )
        assert self.client_id in self.manager.client_handlers
        assert "Client-specific tool" in self.manager.client_handlers[self.client_id]
        assert (
            self.manager.client_handlers[self.client_id]["Client-specific tool"]
            is self.handler
        )

    def test_get_client_tools_returns_only_client_specific_tools_when_no_global(self):
        # Arrange
        self.manager.add_client_tool(self.client_id, self.client_tool, self.handler)

        # Act
        tools = self.manager.get_client_tools(self.client_id)

        # Assert
        assert len(tools) == 1
        assert "Client-specific tool" in tools
        assert tools["Client-specific tool"].name == "Client-specific tool"
        assert (
            tools["Client-specific tool"].description == "Access client-specific tool"
        )

    def test_get_client_tools_returns_global_plus_client_specific_tools(self):
        # Arrange
        self.manager.add_tool(self.global_tool, self.handler)
        self.manager.add_client_tool(self.client_id, self.client_tool, self.handler)

        # Act
        tools = self.manager.get_client_tools(self.client_id)

        # Assert
        assert len(tools) == 2
        assert "Global tool" in tools  # Global tool
        assert "Client-specific tool" in tools  # Client-specific tool
        assert tools["Global tool"].name == "Global tool"
        assert tools["Client-specific tool"].name == "Client-specific tool"

    def test_get_client_tools_client_specific_overrides_global_with_same_name(self):
        # Arrange - add global tool first
        global_tool = Tool(
            name="Generic name",
            description="Global version",
            input_schema=JSONSchema(),
        )
        client_tool = Tool(
            name="Generic name",
            description="Client version",
            input_schema=JSONSchema(),
        )
        self.manager.add_tool(global_tool, self.handler)
        self.manager.add_client_tool(self.client_id, client_tool, self.handler)

        # Act
        tools = self.manager.get_client_tools(self.client_id)

        # Assert
        assert len(tools) == 1
        assert "Generic name" in tools
        assert tools["Generic name"].description == "Client version"
        assert tools["Generic name"] is client_tool

    def test_get_client_tools_returns_only_global_when_no_client_specific(self):
        # Arrange - only global tools
        self.manager.add_tool(self.global_tool, self.handler)

        # Act
        tools = self.manager.get_client_tools(self.client_id)

        # Assert
        assert len(tools) == 1
        assert "Global tool" in tools
        assert tools["Global tool"].description == "Access global tool"

    def test_get_client_tools_returns_empty_when_no_tools_exist(self):
        # Arrange - no tools at all

        # Act
        tools = self.manager.get_client_tools("any-client")

        # Assert
        assert len(tools) == 0
        assert tools == {}

    def test_cleanup_client_removes_all_client_tools_and_handlers(self):
        # Arrange - add multiple client-specific tools
        tool2 = Tool(
            name="second-tool",
            description="Second client tool",
            input_schema=JSONSchema(),
        )
        handler2 = AsyncMock()

        self.manager.add_client_tool(self.client_id, self.client_tool, self.handler)
        self.manager.add_client_tool(self.client_id, tool2, handler2)
        assert len(self.manager.client_tools[self.client_id]) == 2  # Verify setup

        # Act
        self.manager.cleanup_client(self.client_id)

        # Assert
        assert self.client_id not in self.manager.client_tools
        assert self.client_id not in self.manager.client_handlers

    def test_cleanup_client_silently_succeeds_for_unknown_client(self):
        # Arrange - no client tools exist
        assert self.manager.client_tools == {}
        assert self.manager.client_handlers == {}

        # Act & Assert - should not raise any exception
        self.manager.cleanup_client("unknown-client")

        # Verify manager state is unchanged
        assert len(self.manager.client_tools) == 0
        assert len(self.manager.client_handlers) == 0

    def test_cleanup_client_does_not_affect_global_tools(self):
        # Arrange - add both global and client-specific tools
        self.manager.add_tool(self.global_tool, self.handler)
        self.manager.add_client_tool(self.client_id, self.client_tool, self.handler)
        assert len(self.manager.global_tools) == 1  # Verify setup

        # Act
        self.manager.cleanup_client(self.client_id)

        # Assert - global tools remain untouched
        assert len(self.manager.global_tools) == 1
        assert "Global tool" in self.manager.global_tools
        # Client tools are gone
        assert self.client_id not in self.manager.client_tools

    def test_cleanup_client_does_not_affect_other_clients(self):
        # Arrange - add tools for multiple clients
        other_client = "other-client-456"
        other_tool = Tool(
            name="other-tool", description="Other tool", input_schema=JSONSchema()
        )
        other_handler = AsyncMock()

        self.manager.add_client_tool(self.client_id, self.client_tool, self.handler)
        self.manager.add_client_tool(other_client, other_tool, other_handler)
        assert len(self.manager.client_tools) == 2  # Verify setup

        # Act - cleanup only one client
        self.manager.cleanup_client(self.client_id)

        # Assert - other client's tools remain
        assert self.client_id not in self.manager.client_tools
        assert other_client in self.manager.client_tools
        assert len(self.manager.client_tools[other_client]) == 1
        assert "other-tool" in self.manager.client_tools[other_client]


class TestProtocolHandlers:
    """Tests for MCP protocol request handlers."""

    def setup_method(self):
        # Arrange - consistent setup for all tests
        self.manager = ToolManager()
        self.client_id = "test-client-123"
        self.global_tool = Tool(
            name="calculator",
            description="A calculator tool",
            input_schema=JSONSchema(),
        )
        self.client_tool = Tool(
            name="personal-files",
            description="Access personal files",
            input_schema=JSONSchema(),
        )
        self.global_handler = AsyncMock(
            return_value=CallToolResult(content=[TextContent(text="global result")])
        )
        self.client_handler = AsyncMock(
            return_value=CallToolResult(content=[TextContent(text="client result")])
        )

    async def test_handle_list_returns_all_client_tools(self):
        # Arrange
        self.manager.add_tool(self.global_tool, self.global_handler)
        self.manager.add_client_tool(
            self.client_id, self.client_tool, self.client_handler
        )
        request = ListToolsRequest()

        # Act
        result = await self.manager.handle_list(self.client_id, request)

        # Assert
        assert isinstance(result, ListToolsResult)
        assert len(result.tools) == 2
        tool_names = {tool.name for tool in result.tools}
        assert "calculator" in tool_names
        assert "personal-files" in tool_names

    async def test_handle_list_returns_only_global_when_no_client_specific(self):
        # Arrange
        self.manager.add_tool(self.global_tool, self.global_handler)
        request = ListToolsRequest()

        # Act
        result = await self.manager.handle_list(self.client_id, request)

        # Assert
        assert isinstance(result, ListToolsResult)
        assert len(result.tools) == 1
        assert result.tools[0].name == "calculator"

    async def test_handle_list_returns_empty_when_no_tools(self):
        # Arrange - no tools registered
        request = ListToolsRequest()

        # Act
        result = await self.manager.handle_list(self.client_id, request)

        # Assert
        assert isinstance(result, ListToolsResult)
        assert len(result.tools) == 0

    async def test_handle_call_executes_global_tool_handler(self):
        # Arrange
        self.manager.add_tool(self.global_tool, self.global_handler)
        request = CallToolRequest(name="calculator", arguments={})

        # Act
        result = await self.manager.handle_call(self.client_id, request)

        # Assert
        assert isinstance(result, CallToolResult)
        assert result.content[0].text == "global result"
        self.global_handler.assert_awaited_once_with(self.client_id, request)

    async def test_handle_call_executes_client_specific_handler(self):
        # Arrange
        self.manager.add_client_tool(
            self.client_id, self.client_tool, self.client_handler
        )
        request = CallToolRequest(name="personal-files", arguments={})

        # Act
        result = await self.manager.handle_call(self.client_id, request)

        # Assert
        assert isinstance(result, CallToolResult)
        assert result.content[0].text == "client result"
        self.client_handler.assert_awaited_once_with(self.client_id, request)

    async def test_handle_call_client_handler_overrides_global_handler(self):
        # Arrange - same tool name, different handlers
        client_tool_same_name = Tool(
            name="calculator",
            description="Personal calculator",
            input_schema=JSONSchema(),
        )
        self.manager.add_tool(self.global_tool, self.global_handler)
        self.manager.add_client_tool(
            self.client_id, client_tool_same_name, self.client_handler
        )
        request = CallToolRequest(name="calculator", arguments={})

        # Act
        result = await self.manager.handle_call(self.client_id, request)

        # Assert
        assert isinstance(result, CallToolResult)
        assert result.content[0].text == "client result"  # Client handler wins
        self.client_handler.assert_awaited_once_with(self.client_id, request)
        self.global_handler.assert_not_called()

    async def test_handle_call_raises_keyerror_for_unknown_tool(self):
        # Arrange - no tools registered
        request = CallToolRequest(name="nonexistent", arguments={})

        # Act & Assert
        with pytest.raises(KeyError):
            await self.manager.handle_call(self.client_id, request)

    async def test_handle_call_returns_error_result_for_handler_exception(self):
        # Arrange - handler that raises an exception
        failing_handler = AsyncMock(side_effect=RuntimeError("Handler failed"))
        self.manager.add_tool(self.global_tool, failing_handler)
        request = CallToolRequest(name="calculator", arguments={})

        # Act
        result = await self.manager.handle_call(self.client_id, request)

        # Assert
        failing_handler.assert_awaited_once_with(self.client_id, request)
        assert isinstance(result, CallToolResult)
        assert result.is_error is True

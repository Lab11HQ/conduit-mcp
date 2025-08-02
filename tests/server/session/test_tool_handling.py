from unittest.mock import AsyncMock, Mock

from conduit.protocol.base import METHOD_NOT_FOUND, PROTOCOL_VERSION, Error
from conduit.protocol.initialization import (
    Implementation,
    ServerCapabilities,
    ToolsCapability,
)
from conduit.protocol.tools import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    TextContent,
)
from conduit.server.client_manager import ClientState
from conduit.server.message_context import MessageContext
from conduit.server.session import ServerConfig, ServerSession


class TestToolHandling:
    """Test server session tool handling."""

    def setup_method(self):
        self.transport = Mock()
        self.config_with_tools = ServerConfig(
            capabilities=ServerCapabilities(tools=ToolsCapability()),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )
        self.config_without_tools = ServerConfig(
            capabilities=ServerCapabilities(),
            info=Implementation(name="test-server", version="1.0.0"),
            protocol_version=PROTOCOL_VERSION,
        )

        self.list_request = ListToolsRequest()
        self.context = MessageContext(
            client_id="test-client",
            client_state=ClientState(),
            client_manager=AsyncMock(),
            transport=self.transport,
        )

    async def test_list_tools_capability_disabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_without_tools)

        # Act
        result = await session._handle_list_tools(self.context, self.list_request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support tools capability"

    async def test_list_tools_capability_enabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_tools)

        # Mock the tools manager
        expected_result = ListToolsResult(tools=[])
        session.tools.handle_list = AsyncMock(return_value=expected_result)

        # Act
        result = await session._handle_list_tools(self.context, self.list_request)

        # Assert
        assert result == expected_result
        session.tools.handle_list.assert_called_once_with(
            self.context, self.list_request
        )

    async def test_returns_call_tool_result_when_capability_enabled(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_tools)

        expected_result = CallToolResult(
            content=[TextContent(text="Tool executed successfully")],
            is_error=False,
        )

        # Mock the manager to return success
        session.tools.handle_call = AsyncMock(return_value=expected_result)

        request = CallToolRequest(name="test_tool", arguments={"arg1": "value1"})

        # Act
        result = await session._handle_call_tool(self.context, request)

        # Assert
        assert isinstance(result, CallToolResult)
        assert result.content[0].text == "Tool executed successfully"
        assert result.is_error is False

        # Verify manager was called
        session.tools.handle_call.assert_awaited_once_with(self.context, request)

    async def test_rejects_call_tool_when_capability_not_set(self):
        # Arrange
        session = ServerSession(self.transport, self.config_without_tools)
        request = CallToolRequest(name="test_tool", arguments={"arg1": "value1"})

        # Act
        result = await session._handle_call_tool(self.context, request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert result.message == "Server does not support tools capability"

    async def test_returns_method_not_found_when_tool_unknown(self):
        # Arrange
        session = ServerSession(self.transport, self.config_with_tools)

        # Mock the manager to raise KeyError (unknown tool)
        session.tools.handle_call = AsyncMock(side_effect=KeyError("unknown_tool"))

        request = CallToolRequest(name="unknown_tool", arguments={"arg1": "value1"})

        # Act
        result = await session._handle_call_tool(self.context, request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND

        # Verify manager was called
        session.tools.handle_call.assert_awaited_once_with(self.context, request)

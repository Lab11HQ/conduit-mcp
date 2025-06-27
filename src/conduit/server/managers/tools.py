from typing import Awaitable, Callable

from conduit.protocol.content import TextContent
from conduit.protocol.tools import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    Tool,
)


class ToolManager:
    def __init__(self):
        self.registered: dict[str, Tool] = {}
        self.handlers: dict[
            str, Callable[[CallToolRequest], Awaitable[CallToolResult]]
        ] = {}

    def register(
        self,
        tool: Tool,
        handler: Callable[[CallToolRequest], Awaitable[CallToolResult]],
    ) -> None:
        """Register a tool with its handler."""
        self.registered[tool.name] = tool
        self.handlers[tool.name] = handler

    async def handle_list(self, request: ListToolsRequest) -> ListToolsResult:
        """Handle list tools request with pagination support.

        Ignores pagination parameters for now. Can handle cursor, nextCursor,
        filtering, etc.
        """
        return ListToolsResult(tools=list(self.registered.values()))

    async def handle_call(self, request: CallToolRequest) -> CallToolResult:
        try:
            handler = self.handlers[request.name]  # Can raise KeyError -> MCP error
            return await handler(request)
        except KeyError:
            # Re-raise for session to convert to MCP protocol error
            raise
        except Exception as e:
            # Tool execution failed -> domain error in result (LLM can see and
            # self-correct)
            return CallToolResult(
                content=[TextContent(text=f"Tool execution failed: {str(e)}")],
                is_error=True,
            )

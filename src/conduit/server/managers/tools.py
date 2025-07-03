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
        """Register a tool with its handler function.

        Your handler should catch exceptions and return CallToolResult with
        is_error=True and descriptive error content. This gives the LLM useful
        context for recovery. Uncaught exceptions become generic "Tool execution
        failed" messages.

        Args:
            tool: Tool definition with name, description, and schema.
            handler: Async function that processes tool calls. Should return
                CallToolResult even when execution fails.
        """
        self.registered[tool.name] = tool
        self.handlers[tool.name] = handler

    async def handle_list(self, request: ListToolsRequest) -> ListToolsResult:
        """Handle list tools request with pagination support.

        Ignores pagination parameters for now. Can handle cursor, nextCursor,
        filtering, etc.
        """
        return ListToolsResult(tools=list(self.registered.values()))

    async def handle_call(self, request: CallToolRequest) -> CallToolResult:
        """Execute a tool call request.

        Tool execution failures return CallToolResult with is_error=True so the LLM
        can see what went wrong and potentially recover. Unknown tools raise KeyError
        for the session to convert to protocol errors.

        Args:
            request: Tool call request with name and arguments.

        Returns:
            CallToolResult: Tool output or execution error details.

        Raises:
            KeyError: If the requested tool is not registered.
        """
        try:
            handler = self.handlers[request.name]  # Can raise KeyError
            return await handler(request)
        except KeyError:
            # Re-raise for session to convert to protocol error
            raise
        except Exception as e:
            # Tool execution failed -> domain error for LLM to see
            return CallToolResult(
                content=[TextContent(text=f"Tool execution failed: {str(e)}")],
                is_error=True,
            )

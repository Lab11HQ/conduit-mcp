from typing import Awaitable, Callable

from conduit.protocol.content import TextContent
from conduit.protocol.tools import CallToolRequest, CallToolResult, Tool


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

    def list_all(self) -> list[Tool]:
        """Get all registered tools."""
        return list(self.registered.values())

    async def handle_call(self, request: CallToolRequest) -> CallToolResult:
        """Handle a tool call request.

        Unknown tools are out of scope for this manager and should be handled by
        the session. Tool execution failures are domain errors and should be returned
        to the LLM. User handlers should catch and handle their own exceptions by
        returning a CallToolResult with is_error=True and helpful debugging content
        for the host LLM. By default, we return text content with the exception
        message if the tool handler does not catch and handle its own exceptions.

        Args:
            request: The tool call request.

        Returns:
            CallToolResult: The result of the tool call.

        Raises:
            KeyError: If tool not found. This is truly exceptional and should be
                handled by the session.
            Exception: If tool execution fails. This is a domain error and should
                be returned to the LLM.
        """
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

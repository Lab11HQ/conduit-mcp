"""Client-aware tool manager for multi-client server sessions."""

from typing import Awaitable, Callable

from conduit.protocol.content import TextContent
from conduit.protocol.tools import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    Tool,
)

# Type alias for client-aware tool handlers
ClientAwareToolHandler = Callable[[str, CallToolRequest], Awaitable[CallToolResult]]


class ToolManager:
    """Client-aware tool manager for multi-client server sessions.

    Manages global tool registration with client context passed to handlers
    during execution. Tools are registered once but can behave differently
    based on which client is calling them.
    """

    def __init__(self):
        self.registered: dict[str, Tool] = {}
        self.handlers: dict[str, ClientAwareToolHandler] = {}

    def register(
        self,
        tool: Tool,
        handler: ClientAwareToolHandler,
    ) -> None:
        """Register a tool with its client-aware handler function.

        Tools are registered globally but handlers receive client context
        during execution. This allows tools to behave differently per client
        for logging, access control, or personalization.

        Your handler should catch exceptions and return CallToolResult with
        is_error=True and descriptive error content. This gives the LLM useful
        context for recovery. Uncaught exceptions become generic "Tool execution
        failed" messages.

        Args:
            tool: Tool definition with name, description, and schema.
            handler: Async function that processes tool calls with client context.
                Should return CallToolResult even when execution fails.
        """
        self.registered[tool.name] = tool
        self.handlers[tool.name] = handler

    async def handle_list(
        self, client_id: str, request: ListToolsRequest
    ) -> ListToolsResult:
        """Handle list tools request for specific client.

        Returns all registered tools. Could be extended to filter tools
        based on client permissions or capabilities.

        Args:
            client_id: ID of the client requesting tools
            request: List tools request with pagination support

        Returns:
            ListToolsResult: Available tools for this client
        """
        # For now, all clients see all tools
        # Could add client-specific filtering here:
        # tools = [
        # tool for tool in self.registered.values() if
        # self._client_can_access(client_id, tool)
        # ]
        return ListToolsResult(tools=list(self.registered.values()))

    async def handle_call(
        self, client_id: str, request: CallToolRequest
    ) -> CallToolResult:
        """Execute a tool call request for specific client.

        Tool execution failures return CallToolResult with is_error=True so the LLM
        can see what went wrong and potentially recover. Unknown tools raise KeyError
        for the session to convert to protocol errors.

        Args:
            client_id: ID of the client calling the tool
            request: Tool call request with name and arguments

        Returns:
            CallToolResult: Tool output or execution error details

        Raises:
            KeyError: If the requested tool is not registered
        """
        try:
            handler = self.handlers[request.name]  # Can raise KeyError
            return await handler(client_id, request)
        except KeyError:
            # Re-raise for session to convert to protocol error
            raise
        except Exception as e:
            # Tool execution failed -> domain error for LLM to see
            return CallToolResult(
                content=[TextContent(text=f"Tool execution failed: {str(e)}")],
                is_error=True,
            )

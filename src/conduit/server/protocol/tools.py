"""Client-aware tool manager for multi-client server sessions."""

from copy import deepcopy
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
        # Global tools (shared across all clients)
        self.global_tools: dict[str, Tool] = {}
        self.global_handlers: dict[str, ClientAwareToolHandler] = {}

        # Client-specific tools
        self.client_tools: dict[
            str, dict[str, Tool]
        ] = {}  # client_id -> {tool_name: tool}
        self.client_handlers: dict[
            str, dict[str, ClientAwareToolHandler]
        ] = {}  # client_id -> {tool_name: handler}

    # ================================
    # Global tool management
    # ================================

    def add_tool(
        self,
        tool: Tool,
        handler: ClientAwareToolHandler,
    ) -> None:
        """Add a global tool with its client-aware handler function.

        Tools are registered globally and available to all clients. Handlers receive
        client context during execution, allowing tools to behave differently per client
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
        self.global_tools[tool.name] = tool
        self.global_handlers[tool.name] = handler

    def get_tools(self) -> dict[str, Tool]:
        """Get all global tools.

        Returns:
            Dictionary mapping tool names to Tool objects for all global tools.
        """
        return deepcopy(self.global_tools)

    def get_tool(self, name: str) -> Tool | None:
        """Get a specific global tool by name.

        Args:
            name: Name of the tool to retrieve.

        Returns:
            Tool object if found, None otherwise.
        """
        return self.global_tools.get(name)

    def remove_tool(self, name: str) -> None:
        """Remove a global tool by name.

        Silently succeeds if the tool doesn't exist.

        Args:
            name: Name of the tool to remove.
        """
        self.global_tools.pop(name, None)
        self.global_handlers.pop(name, None)

    def clear_tools(self) -> None:
        """Remove all global tools and their handlers."""
        self.global_tools.clear()
        self.global_handlers.clear()

    # ================================
    # Client-specific tool management
    # ================================

    def add_client_tool(
        self,
        client_id: str,
        tool: Tool,
        handler: ClientAwareToolHandler,
    ) -> None:
        """Add a tool for a specific client.

        Client-specific tools are only available to the specified client and can
        override global tools with the same name for that client. Handlers receive
        the client context during execution.

        Args:
            client_id: ID of the client this tool is specific to.
            tool: Tool definition with name, description, and schema.
            handler: Async function that processes tool calls with client context.
                Should return CallToolResult even when execution fails.
        """
        # Initialize client storage if this is the first tool for this client
        if client_id not in self.client_tools:
            self.client_tools[client_id] = {}
            self.client_handlers[client_id] = {}

        # Store the client-specific tool and handler
        self.client_tools[client_id][tool.name] = tool
        self.client_handlers[client_id][tool.name] = handler

    def get_client_tools(self, client_id: str) -> dict[str, Tool]:
        """Get all tools a client can access.

        Returns global tools plus any client-specific tools. Client-specific tools
        override global tools with the same name.

        Args:
            client_id: ID of the client to get tools for.

        Returns:
            Dictionary mapping tool names to Tool objects for this client.
        """

        # Start with global tools
        tools = deepcopy(self.global_tools)

        # Add client-specific tools, with override logging
        if client_id in self.client_tools:
            for name, tool in self.client_tools[client_id].items():
                if name in tools:
                    print(f"Client {client_id} overriding global tool '{name}'")
                tools[name] = tool

        return tools

    def remove_client_tool(self, client_id: str, name: str) -> None:
        """Remove a client-specific tool by name.

        Silently succeeds if the client or tool doesn't exist.

        Args:
            client_id: ID of the client to remove the tool from.
            name: Name of the tool to remove.
        """
        if client_id in self.client_tools:
            self.client_tools[client_id].pop(name, None)
            self.client_handlers[client_id].pop(name, None)

    def cleanup_client(self, client_id: str) -> None:
        """Remove all tools and handlers for a specific client.

        Called when a client disconnects to free up memory and prevent
        stale client-specific tools from accumulating.

        Args:
            client_id: ID of the client to clean up.
        """
        self.client_tools.pop(client_id, None)
        self.client_handlers.pop(client_id, None)

    # ================================
    # Protocol handlers
    # ================================

    async def handle_list(
        self, client_id: str, request: ListToolsRequest
    ) -> ListToolsResult:
        """Handle list tools request for specific client.

        Returns all tools available to this client (global + client-specific).
        Client-specific tools override global tools with the same name.

        Args:
            client_id: ID of the client requesting tools
            request: List tools request with pagination support

        Returns:
            ListToolsResult: Available tools for this client
        """
        tools = self.get_client_tools(client_id)
        return ListToolsResult(tools=list(tools.values()))

    async def handle_call(
        self, client_id: str, request: CallToolRequest
    ) -> CallToolResult:
        """Execute a tool call request for specific client.

        Uses client-specific handler if available, otherwise falls back to global.
        Client-specific handlers override global handlers for the same tool name.

        Tool execution failures return CallToolResult with is_error=True so the LLM
        can see what went wrong and potentially recover. Unknown tools raise KeyError
        for the session to convert to protocol errors.

        Args:
            client_id: ID of the client calling the tool
            request: Tool call request with name and arguments

        Returns:
            CallToolResult: Tool output or execution error details

        Raises:
            KeyError: If the requested tool is not registered for this client
        """
        try:
            # Check for client-specific handler first
            if (
                client_id in self.client_handlers
                and request.name in self.client_handlers[client_id]
            ):
                handler = self.client_handlers[client_id][request.name]
            elif request.name in self.global_handlers:
                handler = self.global_handlers[request.name]
            else:
                raise KeyError(f"Tool '{request.name}' not found")

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

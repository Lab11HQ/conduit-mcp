"""Client-aware tool manager for multi-client server sessions."""

import logging
from copy import deepcopy
from typing import TYPE_CHECKING, Awaitable, Callable

from conduit.protocol.content import TextContent
from conduit.protocol.tools import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    Tool,
)

if TYPE_CHECKING:
    from conduit.server.request_context import RequestContext

ToolHandler = Callable[["RequestContext", CallToolRequest], Awaitable[CallToolResult]]


class ToolManager:
    """
    Manages protocol tool registration and execution for a server.
    """

    def __init__(self):
        self.global_tools: dict[str, Tool] = {}
        self.global_handlers: dict[str, ToolHandler] = {}

        self.client_tools: dict[
            str, dict[str, Tool]
        ] = {}  # client_id -> {tool_name: tool}
        self.client_handlers: dict[
            str, dict[str, ToolHandler]
        ] = {}  # client_id -> {tool_name: handler}

        self.logger = logging.getLogger("conduit.server.protocol.tools")

    # ================================
    # Global tool management
    # ================================

    def add_tool(
        self,
        tool: Tool,
        handler: ToolHandler,
    ) -> None:
        """Add a global tool with its handler function.

        Your handler should catch exceptions and return CallToolResult with
        is_error=True and descriptive error content. This gives the LLM useful
        context for recovery. Uncaught exceptions become generic "Tool execution
        failed" messages.

        Args:
            tool: Tool definition with name, description, and schema.
            handler: Async function that processes tool calls. Must take client_id
                and CallToolRequest as arguments and return a CallToolResult.
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
        """Get a global tool by name.

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
        handler: ToolHandler,
    ) -> None:
        """Add a tool for a specific client.

        Overrides global tools with the same name for this client.

        Args:
            client_id: ID of the client this tool is specific to.
            tool: Tool definition with name, description, and schema.
            handler: Async function that processes tool calls. Must take client_id
                and CallToolRequest as arguments and return a CallToolResult.
        """
        if client_id not in self.client_tools:
            self.client_tools[client_id] = {}
            self.client_handlers[client_id] = {}

        self.client_tools[client_id][tool.name] = tool
        self.client_handlers[client_id][tool.name] = handler

    def get_client_tools(self, client_id: str) -> dict[str, Tool]:
        """Get all tools a client can access.

        Returns global tools plus any client-specific tools.

        Args:
            client_id: ID of the client to get tools for.

        Returns:
            Dictionary mapping tool names to Tool objects for this client.
        """
        tools = deepcopy(self.global_tools)

        if client_id in self.client_tools:
            for name, tool in self.client_tools[client_id].items():
                if name in tools:
                    self.logger.info(
                        f"Client {client_id} overriding global tool '{name}'"
                    )
                tools[name] = tool

        return tools

    def remove_client_tool(self, client_id: str, name: str) -> None:
        """Remove a client-specific tool by name.

        Does not raise an error if the client or tool doesn't exist.

        Args:
            client_id: ID of the client to remove the tool from.
            name: Name of the tool to remove.
        """
        if client_id in self.client_tools:
            self.client_tools[client_id].pop(name, None)
            self.client_handlers[client_id].pop(name, None)

    def cleanup_client(self, client_id: str) -> None:
        """Remove all tools and handlers for a specific client.

        Args:
            client_id: ID of the client to clean up.
        """
        self.client_tools.pop(client_id, None)
        self.client_handlers.pop(client_id, None)

    # ================================
    # Protocol handlers
    # ================================

    async def handle_list(
        self, context: "RequestContext", request: ListToolsRequest
    ) -> ListToolsResult:
        """Lists tools for a specific client.

        Returns all tools available to this client (global + client-specific).
        Client-specific tools override global tools with the same name.

        Args:
            context: Rich request context with client state and helpers
            request: List tools request with pagination support

        Returns:
            ListToolsResult: Available tools for this client
        """
        tools = self.get_client_tools(context.client_id)
        return ListToolsResult(tools=list(tools.values()))

    async def handle_call(
        self, context: "RequestContext", request: CallToolRequest
    ) -> CallToolResult:
        """Execute a tool call request for a specific client.

        Tool execution failures return CallToolResult with is_error=True so the LLM
        can see what went wrong and potentially recover.

        Args:
            context: Rich request context with client state and helpers
            request: Tool call request with name and arguments

        Returns:
            CallToolResult: Tool output or execution error details

        Raises:
            KeyError: If the requested tool is not registered for this client
        """
        try:
            if (
                context.client_id in self.client_handlers
                and request.name in self.client_handlers[context.client_id]
            ):
                handler = self.client_handlers[context.client_id][request.name]
            elif request.name in self.global_handlers:
                handler = self.global_handlers[request.name]
            else:
                raise KeyError(f"Tool '{request.name}' not found")

            return await handler(context, request)
        except KeyError:
            raise
        except Exception as e:
            return CallToolResult(
                content=[TextContent(text=f"Tool execution failed: {str(e)}")],
                is_error=True,
            )

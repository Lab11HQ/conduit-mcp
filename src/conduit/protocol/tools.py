"""
MCP Tools: Turn your LLM into an agent that can actually do things.

Instead of just generating text, your LLM can now:
- Search the web and read documents
- Query databases and APIs
- Write files and run calculations
- Send emails and create calendar events

The flow is straightforward:

1. **Discovery**: LLM asks "What can I do?" via `ListToolsRequest`
2. **Decision**: LLM reads tool descriptions and decides which to use
3. **Execution**: LLM calls the tool with `CallToolRequest`
4. **Use**: Tool returns results (or errors) that LLM can see and use

Note: LLMs consume both results and errors so they can learn from failures and adjust
their approach. The quality of your tool outputs, descriptions, and error messages
determines how effectively the LLM can use your tools.
"""

from typing import Any, Literal

from pydantic import Field

from conduit.protocol.base import (
    Notification,
    PaginatedRequest,
    PaginatedResult,
    ProtocolModel,
    Request,
    Result,
)
from conduit.protocol.content import (
    AudioContent,
    EmbeddedResource,
    ImageContent,
    TextContent,
)


class InputSchema(ProtocolModel):
    """
    JSON schema defining what parameters a tool accepts.

    Always uses type "object" since tools take named parameters, not positional ones.
    Define required parameters to help LLMs provide complete inputs.
    """

    type: Literal["object"] = Field(default="object", frozen=True)
    properties: dict[str, Any] | None = None
    required: list[str] | None = None


class ToolAnnotations(ProtocolModel):
    """
    Behavioral hints about a tool to help LLMs make better decisions.

    These are advisory only—never trust hints from untrusted servers for security
    decisions. They help LLMs understand tool characteristics like safety and scope,
    but don't guarantee the tool's behavior.
    """

    title: str | None = None
    """
    Human-readable title for the tool.
    """

    read_only_hint: bool = Field(default=False, alias="readOnlyHint")
    """
    True if the tool only reads data without making changes.
    """

    destructive_hint: bool = Field(default=True, alias="destructiveHint")
    """
    True if the tool might delete or overwrite existing data. Defaults to True for
    safety.
    """

    idempotent_hint: bool = Field(default=False, alias="idempotentHint")
    """
    True if calling the tool multiple times with same arguments has no additional
    effect.
    """

    open_world_hint: bool = Field(default=True, alias="openWorldHint")
    """
    True if the tool interacts with external systems (web, APIs). False for contained
    tools like memory or math.
    """


class Tool(ProtocolModel):
    """
    A function that LLMs can call to interact with your system.

    Tools are how you extend an LLM's capabilities beyond text generation.
    Each tool defines what it does, what inputs it expects, and provides
    hints about its behavior to help LLMs use it effectively.
    """

    name: str
    """
    Unique identifier for the tool. Use clear, descriptive names like 'search_web' or
    'send_email'.
    """

    description: str | None = None
    """
    Human-readable description of the tool. Clients can use this to improve LLM
    understanding of the tool.
    """

    input_schema: InputSchema = Field(alias="inputSchema")
    """
    JSON schema for the tool's input parameters.
    """

    annotations: ToolAnnotations | None = Field(default=None)
    """
    Optional behavioral hints to help LLMs make better decisions about tool usage.
    """


class ListToolsResult(PaginatedResult):
    """Server's response listing available tools."""

    tools: list[Tool]


class ListToolsRequest(PaginatedRequest):
    """Ask the server what tools are available."""

    method: Literal["tools/list"] = "tools/list"

    @classmethod
    def expected_result_type(cls) -> type[ListToolsResult]:
        return ListToolsResult


class CallToolResult(Result):
    """Result from executing a tool."""

    content: list[TextContent | ImageContent | AudioContent | EmbeddedResource]
    """
    The tool's output, which the LLM can read and understand.
    """

    is_error: bool = Field(default=False, alias="isError")
    """
    True if the tool execution failed. The LLM can see this and try a different
    approach. Use this for tool-level errors, not protocol-level errors.
    """


class CallToolRequest(Request):
    """
    Execute a specific tool with given arguments.
    """

    method: Literal["tools/call"] = "tools/call"
    name: str
    """
    Name of the tool to call.
    """

    arguments: dict[str, Any] | None = None
    """
    Arguments to pass to the tool, matching its input schema.
    """

    @classmethod
    def expected_result_type(cls) -> type[CallToolResult]:
        return CallToolResult


class ToolListChangedNotification(Notification):
    """
    Server notification that available tools have changed.

    Servers can send this anytime without the client subscribing first.
    Useful when tools are added, removed, or modified dynamically.
    """

    method: Literal["notifications/tools/list_changed"] = (
        "notifications/tools/list_changed"
    )

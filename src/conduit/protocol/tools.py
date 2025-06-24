"""
Tool system for extending LLM capabilities beyond text generation.

Tools solve a fundamental limitation: LLMs can describe actions but can't perform them.
By defining callable functions through MCP, you enable LLMs to interact with your
systems, APIs, and data sources automatically based on conversation context.

## The Tool Lifecycle

1. **Discovery** - Clients ask servers "what can you do?" via ListToolsRequest
2. **Selection** - LLMs choose appropriate tools based on descriptions and behavioral
    hints
3. **Execution** - Clients invoke tools with CallToolRequest, passing structured
    arguments
4. **Integration** - Tool results become conversation context the LLM can build upon

## Designing Effective Tools

Tools work best when they represent clear, focused capabilities. Instead of a generic
"database" tool, create specific tools like "search_customers" or "update_inventory".

Remember that LLMs consume your tool outputs. Instead of returning raw JSON payloads
or deeply nested data structures, format results as readable text that an LLM can
understand and work with. A customer search tool should return "Found 3 customers
matching 'Smith': John Smith (ID: 1234, email: john@example.com)..." rather than
a complex object hierarchy.

Use ToolAnnotations to guide LLM decision-making. For example, mark tools as
read-only, destructive, or open-world to help LLMs understand when and how to
use them.

Tool results can include rich content: text responses, images, audio, or embedded
server resources. The error handling model keeps failures visible to the LLM rather
than breaking the conversation flow, enabling intelligent recovery and alternative
approaches.
"""

from typing import Any, Literal

from pydantic import Field

from conduit.protocol.base import (
    BaseMetadata,
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
from conduit.protocol.resources import ResourceLink

ContentBlock = (
    TextContent | ImageContent | AudioContent | EmbeddedResource | ResourceLink
)


class JSONSchema(ProtocolModel):
    """
    JSON schema defining what parameters a tool accepts or returns.

    Always uses type "object" since tools take/return named parameters, not positional
    ones. Define required parameters to help LLMs provide complete inputs.
    """

    type: Literal["object"] = Field(default="object", frozen=True)
    properties: dict[str, Any] | None = None
    required: list[str] | None = None


class ToolAnnotations(ProtocolModel):
    """
    Behavioral hints that guide LLM tool selection and usage patterns.

    When LLMs have multiple tools available, these hints inform strategic
    decision-making. A read-only database tool can be called speculatively
    during information gathering. An idempotent configuration tool can be
    safely retried on failure. A destructive cleanup tool requires careful
    consideration of timing and necessity.

    **Security note**: These are optimization hints, not security guarantees.
    Never rely on annotations from untrusted servers for access control decisions.
    """

    title: str | None = None
    """
    Display name for the tool.
    """

    read_only_hint: bool = Field(default=False, alias="readOnlyHint")
    """
    Indicates tools that observe but don't modify their environment.
    """

    destructive_hint: bool = Field(default=True, alias="destructiveHint")
    """
    Marks tools that may delete or overwrite existing data.
    
    When False, indicates additive-only operations. Defaults to True for
    conservative behavior.
    """

    idempotent_hint: bool = Field(default=False, alias="idempotentHint")
    """
    Indicates operations that can be safely repeated.
    
    Enables automatic retry logic and simplifies error recovery patterns.
    """

    open_world_hint: bool = Field(default=True, alias="openWorldHint")
    """
    Distinguishes tools that interact with external systems versus
    those operating within controlled boundaries.
    
    Web APIs and third-party services are open-world. Internal databases
    and computational tools are closed-world.
    """


class Tool(BaseMetadata):
    """
    A callable function that extends LLM capabilities beyond text generation.

    Tools solve the fundamental limitation of language models: they can describe
    actions but can't perform them. By defining tools, you create a controlled
    interface for LLMs to interact with your systems, APIs, and data sources.

    The LLM automatically determines when to call tools based on conversation
    context, eliminating the need for explicit command parsing or user input.
    """

    description: str | None = None
    """
    Guides the LLM's understanding of when and how to use this tool.
    
    Effective descriptions explain the tool's purpose, appropriate use cases,
    and any relevant constraints or considerations.
    """

    input_schema: JSONSchema = Field(alias="inputSchema")
    """
    JSON Schema defining the tool's parameter structure.
    """

    output_schema: JSONSchema | None = Field(default=None, alias="outputSchema")
    """
    JSON Schema defining the tool's return structure.
    """

    annotations: ToolAnnotations | None = Field(default=None)
    """
    Behavioral hints that inform LLM tool selection strategies.
    """


class ListToolsRequest(PaginatedRequest):
    """
    Discover what capabilities a server offers.

    This is typically the start of the tool usage process. Clients use this to
    ask "what can you do?" The response shapes how the LLM will interact
    with the server throughout the session.
    """

    method: Literal["tools/list"] = "tools/list"

    @classmethod
    def expected_result_type(cls) -> type["ListToolsResult"]:
        return ListToolsResult


class ListToolsResult(PaginatedResult):
    """
    The server's catalog of available capabilities.

    Each tool in this list becomes a function the LLM can call. The server
    is essentially saying "here's what I can do for you"—whether that's
    querying databases, calling APIs, or manipulating files.
    """

    tools: list[Tool]


class CallToolRequest(Request):
    """
    Execute a specific tool with given arguments.

    This is where the LLM puts tools to work—calling functions, querying
    data, or performing actions based on the conversation context.
    """

    method: Literal["tools/call"] = "tools/call"
    name: str
    """
    Name of the tool to execute.
    """

    arguments: dict[str, Any] | None = None
    """
    Arguments for the tool call, structured according to the tool's input schema.
    """

    @classmethod
    def expected_result_type(cls) -> type["CallToolResult"]:
        return CallToolResult


class CallToolResult(Result):
    """
    The outcome of a tool execution.

    Tools can return rich content—text, images, audio, or embedded resources—
    that becomes part of the conversation context. The LLM processes this
    output and decides how to proceed.
    """

    content: list[ContentBlock]
    """
    Tool output that becomes part of the conversation context.

    Content can mix any combination of formats—text, images, audio, or embedded
    resources. Multimodal LLMs can work directly with images and audio, while
    text-focused LLMs may need clients to provide descriptions or transcriptions.
    """

    structured_content: dict[str, Any] | None = Field(
        default=None, alias="structuredContent"
    )
    """
    Structured tool output.
    """

    is_error: bool | None = Field(default=None, alias="isError")
    """
    Indicates tool execution failure while keeping the error visible to the LLM.

    Set to True instead of raising a protocol level error on tool call failure.
    When True, include descriptive error information in the `content` field to help
    the LLM understand what went wrong and potentially recover or try alternative
    approaches. For example: error messages, diagnostic information, or suggestions
    for correcting the tool call.

    Useful for LLM debugging and recovery workflows.
    """


class ToolListChangedNotification(Notification):
    """
    Server notification that its tool catalog has changed.

    Servers send this when tools are added, removed, or modified—perhaps
    when new integrations come online or capabilities are dynamically
    enabled. Clients typically respond by fetching the updated tool list
    to keep the LLM's understanding current.

    Note: No subscription required—servers can broadcast this notification at
    any time during the session.
    """

    method: Literal["notifications/tools/list_changed"] = (
        "notifications/tools/list_changed"
    )

"""
LLM sampling capabilities that let servers invoke the host LLM.

Sampling flips the typical MCP relationship: instead of servers just responding
to LLM requests, they can actively engage the LLM to enhance their own capabilities.
A code analysis server might ask the LLM to explain security implications, or a
database server might request natural language summaries of complex query results.

## The Sampling Flow

1. **Server requests** - Asks to sample the LLM via CreateMessageRequest
2. **User approval** - Client shows the request for human review and approval
3. **LLM invocation** - Client sends approved messages to the selected LLM
4. **Response review** - User sees the LLM's response before sharing with server
5. **Server receives** - Gets the LLM output via CreateMessageResult

## Agentic Capabilities

Sampling enables sophisticated server behaviors: analyzing resources, making
context-aware decisions, generating structured outputs, and handling multi-step
workflows. Servers become active problem-solving partners rather than passive tools.

## Control and Constraints

Users maintain full control throughout the process, but servers should design
for real-world limitations: rate limits, context size bounds, variable response
times, and potential sampling failures. Robust servers handle these gracefully
with fallback behaviors and appropriate error handling.

Servers can express model preferences and include context from other MCP servers,
but clients have final authority over model selection and prompt modification.
"""

from typing import Any, Literal

from pydantic import Field, field_validator

from conduit.protocol.base import ProtocolModel, Request, Result, Role
from conduit.protocol.content import AudioContent, ImageContent, TextContent


class SamplingMessage(ProtocolModel):
    """
    A single message in a conversation with an LLM.

    Used both for messages servers want to send to the LLM (in sampling
    requests) and for messages the LLM generates in response. Can contain
    text, images, or audio depending on the LLM's capabilities.
    """

    role: Role
    """
    Who sent this message - user, assistant, or system.
    """

    content: TextContent | ImageContent | AudioContent
    """
    The message content in the appropriate format.
    """


class ModelHint(ProtocolModel):
    """A hint for model selection."""

    name: str | None = None
    """
    A hint for a model name.
    
    Treated as a substring match: 'claude' matches any Claude model,
    'sonnet' matches Claude Sonnet variants. Clients may map to equivalent
    models from different providers that fill similar niches.
    """


class ModelPreferences(ProtocolModel):
    """
    Server preferences for LLM model selection and behavior.

    Servers can express what kind of model they'd prefer for their sampling
    request, but clients have full discretion to choose any available model.
    This is advisory guidance, not a requirement.
    """

    hints: list[ModelHint] | None = Field(default=None)
    """
    Preferred model hints evaluated in order.
    
    If multiple hints are specified, clients MUST evaluate them in order
    (first match wins). Clients SHOULD prioritize these over numeric
    priorities, but MAY use priorities to select from ambiguous matches.
    """

    cost_priority: float | None = Field(default=None, alias="costPriority")
    """
    How much the server values cost efficiency (0.0 to 1.0).
    
    Higher values suggest preferring cheaper models when quality trade-offs
    are acceptable for the task.
    """

    speed_priority: float | None = Field(default=None, alias="speedPriority")
    """
    How much the server values response speed (0.0 to 1.0).
    
    Higher values suggest preferring faster models when latency matters
    more than maximum capability.
    """

    intelligence_priority: float | None = Field(
        default=None, alias="intelligencePriority"
    )
    """
    How much the server values model capability (0.0 to 1.0).
    
    Higher values suggest preferring the most capable models when
    task complexity demands maximum reasoning ability.
    """

    @field_validator("cost_priority", "speed_priority", "intelligence_priority")
    @classmethod
    def validate_priority(cls, v: float | None) -> float | None:
        if v is not None and (v < 0 or v > 1):
            raise ValueError(f"Priority must be between 0 and 1, got {v}")
        return v


class CreateMessageRequest(Request):
    """
    Server request to invoke the host LLM for intelligent processing.

    This flips the typical relationship—instead of just responding to LLM calls,
    servers can actively engage the LLM to enhance their own capabilities.
    A code analysis server might ask the LLM to explain security implications,
    or a database server might request natural language summaries of query results.

    The client maintains full control: users see what the server wants to ask
    and can approve or reject the request before any LLM sampling occurs.
    """

    method: Literal["sampling/createMessage"] = "sampling/createMessage"
    messages: list[SamplingMessage]
    """
    The conversation the server wants to have with the LLM.
    """

    max_tokens: int = Field(alias="maxTokens")
    """
    Maximum response length the server is requesting.
    """

    preferences: ModelPreferences | None = Field(default=None, alias="modelPreferences")
    """
    Server's preferred model characteristics.

    The client may ignore these preferences and choose any available model.
    """
    system_prompt: str | None = Field(default=None, alias="systemPrompt")
    """
    Optional system prompt to guide the LLM's behavior.

    The client may modify or omit this prompt entirely.
    """

    include_context: Literal["none", "thisServer", "allServers"] | None = Field(
        default=None, alias="includeContext"
    )
    """
    Request to include context from MCP servers in the prompt.
    
    Enables cross-server collaboration by sharing relevant context from the current
    session. The client may ignore this request.
    """

    temperature: float | int | None = None
    """
    Randomness level for the LLM response.
    
    Higher values make the response more creative and varied, while lower values make
    it more deterministic and consistent.
    """
    stop_sequences: list[str] | None = Field(default=None, alias="stopSequences")
    """
    Strings that should end the LLM's response early.
    """

    llm_metadata: dict[str, Any] | None = None
    """
    LLM provider-specific parameters for advanced control.

    This passes through to your specific LLM provider for features not
    covered by the standard MCP parameters. Format depends entirely
    on your provider's API.
    """

    @classmethod
    def from_protocol(cls, data: dict[str, Any]) -> "CreateMessageRequest":
        """Override base Request method to convert from protocol-level representation.

        Handles the spec's dual metadata fields:
        - `_meta` becomes our standard `metadata` field (MCP metadata)
        - `metadata` becomes our `llm_metadata` field (LLM provider metadata)
        """
        # Extract protocol structure
        params = data.get("params", {})
        meta = params.get("_meta", {})

        # Build kwargs for the constructor
        kwargs = {
            "method": data["method"],
            "progress_token": meta.get("progressToken"),
        }

        # Handle MCP metadata (excluding progressToken which we handle specially)
        if meta:
            general_meta = {k: v for k, v in meta.items() if k != "progressToken"}
            if general_meta:
                kwargs["metadata"] = general_meta

        # Handle LLM metadata specially
        if "metadata" in params:
            llm_meta = params["metadata"]
            if llm_meta:  # Only set if non-empty
                kwargs["llm_metadata"] = llm_meta

        # Add other fields, respecting aliases
        for field_name, field_info in cls.model_fields.items():
            if field_name in {"method", "progress_token", "metadata", "llm_metadata"}:
                continue

            param_key = field_info.alias if field_info.alias else field_name
            if param_key in params:
                kwargs[field_name] = params[param_key]

        return cls(**kwargs)

    def to_protocol(self) -> dict[str, Any]:
        """Override base Request method to convert to protocol-level representation.

        Handles the spec's dual metadata fields (both `_meta` and `metadata`) by
        mapping:
        - Our `metadata` field → `_meta` (MCP metadata)
        - Our `llm_metadata` field → `metadata` (LLM provider metadata)
        """
        # Get the base params (excluding our special metadata handling)
        params = self.model_dump(
            exclude={"method", "progress_token", "metadata", "llm_metadata"},
            by_alias=True,
            exclude_none=True,
            mode="json",
        )

        # Handle LLM provider metadata directly in params
        if self.llm_metadata:
            params["metadata"] = self.llm_metadata

        # Handle MCP protocol metadata in _meta
        meta: dict[str, Any] = {}
        if self.metadata:
            meta.update(self.metadata)
        if self.progress_token is not None:
            meta["progressToken"] = self.progress_token

        if meta:
            params["_meta"] = meta

        result: dict[str, Any] = {"method": self.method}
        if params:
            result["params"] = params

        return result

    @classmethod
    def expected_result_type(cls) -> type["CreateMessageResult"]:
        return CreateMessageResult


class CreateMessageResult(Result):
    """
    The LLM's response to a server's sampling request.

    Contains the message generated by the LLM along with metadata about the
    generation process. Users have already approved sharing this response with
    the requesting server.
    """

    # From SamplingMessage
    role: Role
    """
    The role of the message sender (typically 'assistant' for LLM responses).
    """
    content: TextContent | ImageContent | AudioContent
    """
    The LLM's response to the server's request.
    """

    # Own fields
    model: str
    """
    The specific model that generated this response.
    """

    stop_reason: Literal["endTurn", "stopSequence", "maxTokens"] | str | None = Field(
        default=None, alias="stopReason"
    )
    """
    Why the LLM stopped generating.
    
    Common reasons: 'endTurn' (natural completion), 'stopSequence' (hit a
    stop string), 'maxTokens' (reached length limit).
    """

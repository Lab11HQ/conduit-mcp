from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from conduit.protocol.base import ProtocolModel, Request, Result, Role
from conduit.protocol.content import AudioContent, ImageContent, TextContent


class SamplingMessage(ProtocolModel):
    """Describes a message issued to or received from an LLM API."""

    role: Role
    content: TextContent | ImageContent | AudioContent


ModelHint = Annotated[str, "Hint for the model to use."]


class ModelPreferences(ProtocolModel):
    """
    Preferences for the model to use.
    """

    hints: list[ModelHint] | None = Field(default=None)
    cost_priority: float | None = Field(default=None, alias="costPriority")
    speed_priority: float | None = Field(default=None, alias="speedPriority")
    intelligence_priority: float | None = Field(
        default=None, alias="intelligencePriority"
    )

    @field_validator("cost_priority", "speed_priority", "intelligence_priority")
    @classmethod
    def validate_priority(cls, v: float | None) -> float | None:
        if v is not None and (v < 0 or v > 1):
            raise ValueError(f"Priority must be between 0 and 1, got {v}")
        return v


class CreateMessageRequest(Request):
    """
    Request to create a message.
    """

    method: Literal["sampling/createMessage"] = "sampling/createMessage"
    messages: list[SamplingMessage]
    max_tokens: int = Field(alias="maxTokens")
    preferences: ModelPreferences | None = Field(default=None, alias="modelPreferences")
    system_prompt: str | None = Field(default=None, alias="systemPrompt")
    include_context: Literal["none", "thisServer", "allServers"] | None = Field(
        default=None, alias="includeContext"
    )
    temperature: float | int | None = None
    stop_sequences: list[str] | None = Field(default=None, alias="stopSequences")
    llm_metadata: dict[str, Any] | None = None
    """
    LLM provider-specific metadata (from the spec's "metadata" field).

    This is separate from MCP metadata - use this for parameters that your
    LLM provider understands but aren't part of the MCP specification.
    The format depends entirely on your LLM provider.
    """

    @classmethod
    def from_protocol(cls, data: dict[str, Any]) -> "CreateMessageRequest":
        """Convert from protocol-level representation.

        Handles the spec's dual metadata fields:
        - `_meta` becomes our standard `metadata` field (MCP metadata)
        - `metadata` becomes our `llm_metadata` field (LLM provider metadata)

        This separation makes it clear which metadata goes where.
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
        """Convert to protocol-level representation.

        Handles the spec's dual metadata fields by mapping:
        - Our `metadata` field → `_meta` (MCP metadata)
        - Our `llm_metadata` field → `metadata` (LLM provider metadata)

        This maintains wire compatibility while keeping the Python API clear.
        """
        # Get the base params (excluding our special metadata handling)
        params = self.model_dump(
            exclude={"method", "progress_token", "metadata", "llm_metadata"},
            by_alias=True,
            exclude_none=True,
            mode="json",
        )

        # Handle LLM metadata directly in params
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
    """The client's response to a sampling/create_message request from the server."""

    # From SamplingMessage
    role: Role
    content: TextContent | ImageContent | AudioContent

    # Own fields
    model: str
    """The name of the model that generated the message."""
    stop_reason: Literal["endTurn", "stopSequence", "maxTokens"] | str | None = Field(
        default=None, alias="stopReason"
    )
    """The reason why sampling stopped, if known."""

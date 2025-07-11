"""
Core MCP protocol types for building robust JSON-RPC communication.

This module defines the fundamental building blocks of Model Context Protocol:
requests that ask for something, results that deliver what you asked for,
notifications that broadcast events, and errors when things go wrong.

## The MCP Conversation

MCP communication follows a simple pattern:

1. **Requests** - "Can you list your tools?" or "Please call this function"
2. **Results** - "Here are my tools" or "Function returned this value"
3. **Notifications** - "Progress update: 50% complete" (no response expected)
4. **Errors** - "That tool doesn't exist" (when requests fail)

Most applications build on these primitives rather than using them directly,
but understanding this foundation helps when debugging and contributing.
"""

import traceback
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

PROTOCOL_VERSION = "2025-06-18"
RequestId = int | str
ProgressToken = int | str
Cursor = str
Role = Annotated[
    Literal["user", "assistant"],
    "Sender or recipient of messages and data in a conversation.",
]


class ProtocolModel(BaseModel):
    model_config = ConfigDict(
        extra="allow", validate_by_alias=True, validate_by_name=True
    )


class Request(ProtocolModel):
    """
    Foundation for all MCP request messages.

    Every MCP request—from initialization handshakes to tool calls—inherits from
    this base class. While you'll typically work with concrete types like
    `InitializeRequest` or `ListToolsRequest`, they all share this common structure.

    Progress tokens surface at the top level for easy access. Metadata stays
    flexible for whatever context you need to pass along. The protocol translation
    happens automatically—you work with clean Python objects, and the JSON-RPC
    formatting takes care of itself.

    Create any request and get spec compliance, serialization, and proper response
    pairing.
    """

    method: str
    """
    The RPC method name for this request.
    
    This identifies which operation the server should perform, like "initialize" 
    or "tools/list". Each concrete request type sets this automatically.
    """

    progress_token: ProgressToken | None = None
    """
    Optional token to track progress for long-running operations.
    
    When provided, the server can send progress notifications back to the client
    using this token as an identifier.
    """

    metadata: dict[str, Any] | None = Field(default=None)
    """
    Optional metadata for the request.
    
    Use this for additional context that doesn't fit the standard request fields.
    Note: Don't put progress tokens here—use the dedicated `progress_token` field
    instead for proper handling. If you set both, the `progress_token` field takes
    precedence.
    """

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_progress_token_in_metadata(
        cls, metadata: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Validate progress tokens in metadata and guide users to the right field.

        While you can include a progressToken in metadata, we recommend using
        the dedicated `progress_token` field instead. This validator ensures
        any tokens in metadata are properly typed and reminds you about the
        cleaner alternative.

        Raises:
            ValueError: If progressToken in metadata is not a string or integer
        """
        if metadata and "progressToken" in metadata:
            token = metadata["progressToken"]
            if not isinstance(token, str | int):
                raise ValueError(
                    f"progressToken in metadata must be str or int, got "
                    f"{type(token).__name__}. Consider using the progress_token field "
                    "instead."
                )
        return metadata

    @classmethod
    def from_protocol(cls, data: dict[str, Any]) -> Self:
        """Create a request instance from raw JSON-RPC protocol data.

        Takes the nested JSON-RPC format that MCP servers expect and transforms
        it into a clean Python object. Progress tokens get pulled up from the
        metadata hierarchy, and all fields map to their Pythonic equivalents.


        Note: This expects the full JSON-RPC message structure, while `to_protocol`
        returns only the MCP request portion.

        Args:
            data: Raw JSON-RPC request data with method, params, and optional metadata

        Returns:
            A properly constructed request instance
        """

        # Extract protocol structure
        params = data.get("params", {})
        meta = params.get("_meta", {})

        # Build kwargs for the constructor
        kwargs = {
            "method": data["method"],
            "progress_token": meta.get("progressToken"),
        }

        # Handle general metadata (excluding progressToken which we handle specially)
        if meta:
            general_meta = {k: v for k, v in meta.items() if k != "progressToken"}
            if general_meta:
                kwargs["metadata"] = general_meta

        # Add subclass-specific fields, respecting aliases
        for field_name, field_info in cls.model_fields.items():
            if field_name in {"method", "progress_token", "metadata"}:
                continue

            param_key = field_info.alias if field_info.alias else field_name
            if param_key in params:
                kwargs[field_name] = params[param_key]

        return cls(**kwargs)

    def to_protocol(self) -> dict[str, Any]:
        """Convert this request to MCP protocol format.

        Transforms our Pythonic representation into the nested JSON-RPC structure
        that MCP expects. Progress tokens and metadata get properly positioned in
        the `_meta` object, and field names use their protocol aliases.

        Note: This creates the MCP request structure, not the full JSON-RPC
        envelope. The `jsonrpc` and `id` fields are handled separately.

        Returns:
            An MCP-compatible request dictionary with method and params
        """
        params = self.model_dump(
            exclude={"method", "progress_token", "metadata"},
            by_alias=True,
            exclude_none=True,
            mode="json",
        )

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
    def expected_result_type(cls) -> type["Result"]:
        """Return the result type this request expects.

        This enables type-safe request-response pairing and helps downstream
        code correctly handle responses. Each concrete request class overrides
        this to return its specific result type.

        Returns:
            The Result subclass this request expects
        """
        raise NotImplementedError(
            "Subclasses must define this method to return their expected result type."
        )


class PaginatedRequest(Request):
    """
    Base class for MCP requests that handle large result sets through pagination.

    When you're dealing with operations that might return hundreds or thousands
    of items—like listing all available tools or resources—pagination keeps
    responses manageable. Include a cursor to continue from where a previous
    request left off.

    The cursor is opaque: don't try to parse it or construct your own. Just pass along
    whatever the sender gave you in the previous response.
    """

    cursor: Cursor | None = None
    """
    Pagination token for continuing from a previous request.
    
    Leave this None for the first page, then use the cursor from the sender's
    response to get subsequent pages.
    """


class Result(ProtocolModel):
    """
    Base class for MCP results - successful responses to requests.

    When a server successfully handles your request, it sends back a result.
    Each request type has its own result type: `InitializeRequest` gets an
    `InitializeResult`, `ListToolsRequest` gets a `ListToolsResult`, and so on.

    Results carry the actual data you requested: tool lists, resource content,
    initialization parameters, etc.
    """

    metadata: dict[str, Any] | None = Field(default=None)
    """
    Additional result metadata.
    """

    @classmethod
    def from_protocol(cls, data: dict[str, Any]) -> Self:
        """Create a result instance from raw JSON-RPC protocol data.

        Transforms the nested JSON-RPC format into a clean Python object.
        Extracts the actual result data from the response envelope and maps
        fields to their Pythonic equivalents.

        Args:
            data: Raw JSON-RPC response data with result and optional metadata

        Returns:
            A properly constructed result instance
        """

        # Extract result
        result_data = data["result"]

        # Extract metadata
        meta = result_data.get("_meta", {})

        # Build kwargs for the constructor
        kwargs: dict[str, Any] = {}

        # Handle metadata
        if meta:
            kwargs["metadata"] = meta

        # Add subclass-specific fields, respecting aliases
        for field_name, field_info in cls.model_fields.items():
            if field_name == "metadata":
                continue

            # Use the alias if it exists, otherwise use the field name
            param_key = field_info.alias if field_info.alias else field_name

            if param_key in result_data:
                kwargs[field_name] = result_data[param_key]

        return cls(**kwargs)

    def to_protocol(self) -> dict[str, Any]:
        """Convert this result to MCP protocol format.

        Transforms our Pythonic representation into the nested structure that
        MCP expects. Metadata gets positioned in the `_meta` object, and field
        names use their protocol aliases.

        Note: This creates the result payload that goes inside the JSON-RPC
        response envelope.

        Returns:
            An MCP-compatible result dictionary
        """
        result = self.model_dump(
            exclude={"metadata"},
            by_alias=True,
            exclude_none=True,
            mode="json",
        )

        # Add metadata if present
        if self.metadata:
            result["_meta"] = self.metadata

        return result


class PaginatedResult(Result):
    """
    Base class for MCP results that return data in chunks.

    When you request a large dataset, the sender returns a page of results
    along with a cursor. If there's a `next_cursor`, more data is available.
    Just pass that cursor to your next request to continue where you left off.

    No cursor means you've reached the end of the dataset.
    """

    next_cursor: Cursor | None = Field(default=None, alias="nextCursor")
    """
    Cursor for the next page of results.
    
    None means you've got everything. Otherwise, use this value in your
    next request to continue pagination.
    """


# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# Custom error codes
PROTOCOL_VERSION_MISMATCH = -32001


class Error(ProtocolModel):
    """
    Base class for MCP errors - when requests can't be completed.

    Errors tell you what went wrong and why. They carry error codes, human-readable
    messages, and optional data for debugging. Python exceptions get formatted
    automatically into the data field for easy troubleshooting.
    """

    code: int
    """
    Error type code.
    """

    message: str
    """
    Human readable error message.
    """

    data: Any = None
    """
    Additional error context - can be any JSON-serializable value.

    Python exceptions passed here get automatically formatted as tracebacks
    for convenience, but any data type is valid per the MCP specification.
    """

    @field_validator("data", mode="before")
    @classmethod
    def transform_data(cls, value: Any) -> Any:
        """Automatically format Python exceptions as readable tracebacks.

        This convenience feature converts Exception objects into formatted
        traceback strings, making error data more useful for debugging.
        All other data types pass through unchanged.
        """
        if isinstance(value, Exception):
            return cls._format_exception(value)
        return value

    @staticmethod
    def _format_exception(exc: Exception) -> str:
        """Format an exception as a complete traceback string.

        Includes the exception type, message, and full stack trace in a
        format similar to what Python prints for unhandled exceptions.
        """
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    def to_protocol(self) -> dict[str, Any]:
        """Convert this error to MCP protocol format.

        Creates the error object that goes inside a JSON-RPC error response.
        Unlike other message types, errors have a flat structure that maps
        directly to the protocol format.

        Note: This creates the error payload, not the full JSON-RPC error
        envelope. The error gets wrapped at the JSON-RPC layer.

        Returns:
            An MCP-compatible error dictionary with code, message, and optional data
        """
        return self.model_dump(exclude_none=True, mode="json")

    @classmethod
    def from_protocol(cls, data: dict[str, Any]) -> "Error":
        """Create an error instance from raw JSON-RPC protocol data.

        Extracts error information from the JSON-RPC error envelope and
        creates a properly typed Error instance. The automatic exception
        formatting happens during construction if needed.

        Args:
            data: Raw JSON-RPC error response with error object

        Returns:
            A properly constructed Error instance
        """
        error_data = data["error"]
        return cls.model_validate(
            {
                "code": error_data["code"],
                "message": error_data["message"],
                "data": error_data.get("data"),
            }
        )


class Notification(ProtocolModel):
    """
    Base class for MCP notifications - fire-and-forget messages.

    Notifications handle events that don't need responses: progress updates,
    resource changes, alerts, etc.

    Think of them like broadcasting "hey, this happened" rather than asking
    "can you do this?" The recipient processes the notification but doesn't
    send anything back.
    """

    method: str
    """
    The notification type, like "notifications/progress" or "notifications/cancelled".
    """

    metadata: dict[str, Any] | None = Field(default=None)
    """
    Additional context for the notification.
    """

    @classmethod
    def from_protocol(cls, data: dict[str, Any]) -> Self:
        """Create a notification instance from raw JSON-RPC protocol data.

        Transforms the nested JSON-RPC format into a clean Python object.
        Unlike requests, notifications have simpler metadata handling since
        they don't use progress tokens directly.

        Args:
            data: Raw JSON-RPC notification data with method and params

        Returns:
            A properly constructed notification instance
        """

        # Extract params
        params = data.get("params", {})
        meta = params.get("_meta")

        # Build kwargs for the constructor
        kwargs = {
            "method": data["method"],
        }
        if meta:
            kwargs["metadata"] = meta

        # Add subclass-specific fields, respecting aliases
        for field_name, field_info in cls.model_fields.items():
            if field_name == "method":
                continue

            # Use the alias if it exists, otherwise use the field name
            param_key = field_info.alias if field_info.alias else field_name

            if param_key in params:
                kwargs[field_name] = params[param_key]

        return cls(**kwargs)

    def to_protocol(self) -> dict[str, Any]:
        """Convert this notification to MCP protocol format.

        Transforms our Pythonic representation into the nested JSON-RPC structure
        that MCP expects. Metadata gets positioned in the `_meta` object, and
        field names use their protocol aliases.

        Note: Like requests, this creates the MCP notification structure without
        the full JSON-RPC envelope.

        Returns:
            An MCP-compatible notification dictionary with method and params
        """
        params = self.model_dump(
            exclude={"method", "metadata"},
            by_alias=True,
            exclude_none=True,
            mode="json",
        )
        # Attribute is defined on all subclasses but not on the base class. Ignore
        # linter error.
        result: dict[str, Any] = {"method": self.method}  # type: ignore[attr-defined]

        if self.metadata:
            params["_meta"] = self.metadata

        if params:
            result["params"] = params
        return result


class BaseMetadata(ProtocolModel):
    """
    Base interface for metadata with name (identifier) and title (display name).

    This interface is used across multiple MCP types to provide consistent
    naming and display conventions.
    """

    name: str
    """
    Identifier intended for programmatic or logical use.
    
    Used as a display name in past specs or as a fallback when title isn't present.
    """

    title: str | None = None
    """
    Human-readable display name optimized for UI and end-user contexts.
    
    Designed to be easily understood even by those unfamiliar with domain-specific
    terminology. If not provided, the name should be used for display (except for
    Tool, where `annotations.title` should be given precedence over using `name`,
    if present).
    """

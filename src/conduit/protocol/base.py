import traceback
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

PROTOCOL_VERSION = "2025-03-26"
RequestId = Annotated[
    int | str, "Unique identifier for a request. Can be a string or integer."
]
ProgressToken = Annotated[
    str | int, "Token used to track progress of long-running operations."
]
Cursor = Annotated[str, "Opaque string used for pagination in list operations."]
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

    This base class bridges the gap between Python's natural idioms and the JSON-RPC
    format for MCP requests. While you'll work with concrete request types like
    `InitializeRequest` or `ListToolsRequest`, they all inherit this common structure
    and behavior.

    The key insight: MCP's TypeScript spec uses nested structures and camelCase that
    feel foreign in Python. So we flatten complex hierarchies, use snake_case throughout,
    and surface important fields at intuitive levels—like putting `progress_token` at
    the top level instead of buried in `params._meta.progressToken`.

    When you create any MCP request, you're getting:
    - Clean, snake_case Python interfaces
    - Automatic translation to/from the nested protocol format
    - Transparent progress token handling
    - Validation that ensures spec compliance

    The `from_protocol` and `to_protocol` methods handle the format translation—
    you work with Pythonic objects, we handle JSON-RPC serialization.
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
        """Create a request instance from JSON-RPC protocol data.

        This method handles the translation from MCP's nested JSON-RPC format
        to our flattened Python representation. It extracts the method name,
        pulls progress tokens out of the metadata hierarchy, and maps any
        subclass-specific fields using their aliases.

        The heavy lifting happens here so that everywhere else we can work with
        clean Python objects instead of nested dictionaries.

        Args:
            data: Raw JSON-RPC request data with method, params, and optional metadata

        Returns:
            A properly constructed request instance with all fields populated
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

        This method takes our clean Python representation and converts it to
        the nested structure that MCP expects—progress tokens get moved into
        `params._meta.progressToken`, field names use their camelCase aliases,
        and everything gets properly nested.

        Note: This creates the MCP request structure, not the full JSON-RPC
        envelope. The `jsonrpc` and `id` fields are handled separately by
        the JSON-RPC layer.

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


class PaginatedRequest(Request):
    """
    Base class for MCP requests that support pagination.

    Includes an opaque cursor representing the current pagination position.
    If provided, the server should return results starting after this cursor.
    """

    cursor: Cursor | None = None
    """
    Opaque pagination token for retrieving the next page of results.
    """


class Notification(ProtocolModel):
    """
    Base class for MCP notifications.

    Notifications are one-way messages that don't expect a response.
    """

    method: str
    """
    The method of the notification.
    """

    metadata: dict[str, Any] | None = Field(default=None)
    """
    Additional notification metadata.
    """

    @classmethod
    def from_protocol(cls, data: dict[str, Any]) -> Self:
        """Convert from protocol-level representation"""

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
        """Convert to protocol-level representation"""
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


class Result(ProtocolModel):
    """
    Base class for MCP results.

    Results are responses to requests. Each request type has a corresponding result
    type.
    """

    metadata: dict[str, Any] | None = Field(default=None)
    """
    Additional result metadata.
    """

    @classmethod
    def from_protocol(cls, data: dict[str, Any]) -> Self:
        """Convert from protocol-level representation."""

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
        """Convert to protocol-level representation"""
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
    Base class for MCP results that support pagination.

    Includes an opaque token representing the pagination position after the last
    returned result. If present, there may be more results available.
    """

    next_cursor: Cursor | None = Field(default=None, alias="nextCursor")
    """
    Token for retrieving the next page, if more results exist.
    """


PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class Error(ProtocolModel):
    """
    MCP error with automatic exception formatting.

    Example:
        Error(code=500, message="Server error", data=some_exception)
    """

    code: int
    """
    Error type code.
    """

    message: str
    """
    Human readable error message.
    """

    data: str | dict[str, Any] | None = None
    """
    Additional error details. Accepts strings, dicts, or Exceptions.
    Exceptions are automatically converted to formatted tracebacks.
    """

    @field_validator("data", mode="before")
    @classmethod
    def transform_data(cls, value: Any) -> Any:
        if isinstance(value, Exception):
            return cls._format_exception(value)
        return value

    def to_protocol(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True, mode="json")

    @staticmethod
    def _format_exception(exc: Exception) -> str:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    @classmethod
    def from_protocol(cls, data: dict[str, Any]) -> "Error":
        error_data = data["error"]
        return cls.model_validate(
            {
                "code": error_data["code"],
                "message": error_data["message"],
                "data": error_data.get("data"),
            }
        )

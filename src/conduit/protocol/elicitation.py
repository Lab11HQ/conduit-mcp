from typing import Literal

from pydantic import Field

from conduit.protocol.base import ProtocolModel, Request, Result


class BaseSchemaDefinition(ProtocolModel):
    """Base class for primitive schema definitions."""

    title: str | None = None
    description: str | None = None


class StringSchema(BaseSchemaDefinition):
    """
    Schema for text input fields.

    Client may render as text inputs, textareas, or formatted fields
    (email, date, etc.).
    """

    type: Literal["string"] = "string"
    min_length: int | None = Field(default=None, alias="minLength")
    max_length: int | None = Field(default=None, alias="maxLength")
    format: Literal["email", "uri", "date", "date-time"] | None = None


class NumberSchema(BaseSchemaDefinition):
    """
    Schema for numeric input fields.

    Client may render as number inputs with optional min/max constraints.
    """

    type: Literal["number", "integer"]
    minimum: int | float | None = None
    maximum: int | float | None = None


class BooleanSchema(BaseSchemaDefinition):
    """
    Schema for yes/no input fields.

    Client may render as checkboxes or toggle switches.
    """

    type: Literal["boolean"] = "boolean"
    default: bool | None = None


class EnumSchema(BaseSchemaDefinition):
    """
    Schema for single-choice selection fields.

    Client may render as dropdowns, radio buttons, or select lists.
    """

    type: Literal["string"] = "string"
    enum: list[str]
    enum_names: list[str] | None = Field(default=None, alias="enumNames")


PrimitiveSchemaDefinition = StringSchema | NumberSchema | BooleanSchema | EnumSchema


class RequestedSchema(ProtocolModel):
    """
    Simplified JSON Schema for dynamic form generation.

    Restricted to primitive types to ensure all MCP clients can render
    user-friendly forms without complex nested object handling.
    """

    type: Literal["object"] = "object"
    properties: dict[str, PrimitiveSchemaDefinition]
    required: list[str] | None = None


class ElicitRequest(Request):
    """
    Request from server to elicit a additional information from the user.
    """

    method: Literal["elicitation/create"] = "elicitation/create"
    message: str
    """
    The message to present to the user.
    """

    requested_schema: RequestedSchema = Field(alias="requestedSchema")
    """
    Strict subset of JSON Schema that restricts the type of information
    that can be requested from the user. Only top-level properties are
    allowed.
    """

    @classmethod
    def expected_result_type(cls) -> type["ElicitResult"]:
        return ElicitResult


class ElicitResult(Result):
    """
    Result of the elicitation request.
    """

    action: Literal["accept", "decline", "cancel"]
    """
    User response to the elicitation request.

    Accept: The user provided the requested information.
    Decline: The user declined to provide the requested information.
    Cancel: The user dismissed the elicitation request without
        making an explicit choice.
    """

    content: dict[str, str | float | int | bool] | None = None
    """
    Submitted user response. Only present if the action is "accept".
    """

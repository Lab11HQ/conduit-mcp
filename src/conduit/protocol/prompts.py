from typing import Literal

from pydantic import Field

from conduit.protocol.base import (
    Notification,
    PaginatedRequest,
    PaginatedResult,
    ProtocolModel,
    Request,
    Result,
    Role,
)
from conduit.protocol.content import (
    AudioContent,
    EmbeddedResource,
    ImageContent,
    TextContent,
)


class PromptArgument(ProtocolModel):
    """
    Describes an argument that a prompt can accept.
    """

    name: str
    description: str | None = None
    """
    Human-readable description of the argument.
    """

    required: bool = Field(default=False)
    """
    Whether the argument must be provided. Defaults to False.
    """


class Prompt(ProtocolModel):
    """
    A prompt or prompt template the server offers.

    Note the prompt content is in PromptMessage objects.
    """

    name: str
    description: str | None = None
    arguments: list[PromptArgument] | None = None
    """
    List of arguments used for templating the prompt.
    """


class PromptReference(ProtocolModel):
    """
    Reference to a prompt.
    """

    type: Literal["ref/prompt"] = "ref/prompt"
    name: str


class PromptMessage(ProtocolModel):
    """
    Describes a message as a part of a prompt.
    """

    role: Role
    content: TextContent | ImageContent | AudioContent | EmbeddedResource


class ListPromptsRequest(PaginatedRequest):
    """
    Sent by client to list available prompts and prompt templates on the server.
    """

    method: Literal["prompts/list"] = "prompts/list"

    @classmethod
    def expected_result_type(cls) -> type["ListPromptsResult"]:
        return ListPromptsResult


class ListPromptsResult(PaginatedResult):
    """
    Response containing available prompts and pagination info.
    """

    prompts: list[Prompt]
    """
    List of available prompts.
    """


class GetPromptRequest(Request):
    """
    Sent by client to get a specific prompt or prompt template from the server.

    If the prompt is a template, the server will return a prompt with the arguments
    filled in.
    """

    method: Literal["prompts/get"] = "prompts/get"
    name: str
    """
    The name of the prompt or prompt template.
    """

    arguments: dict[str, str] | None = None
    """
    Arguments to use for templating the prompt.
    """

    @classmethod
    def expected_result_type(cls) -> type["GetPromptResult"]:
        return GetPromptResult


class GetPromptResult(Result):
    """
    Response containing the prompt or prompt template.
    """

    description: str | None = None
    """
    Human-readable description of the prompt or prompt template.
    """

    messages: list[PromptMessage]
    """
    The prompt or prompt template messages.
    """


class PromptListChangedNotification(Notification):
    method: Literal["notifications/prompts/list_changed"] = (
        "notifications/prompts/list_changed"
    )

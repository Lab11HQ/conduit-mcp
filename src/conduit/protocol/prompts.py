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
    Role,
)
from conduit.protocol.content import (
    AudioContent,
    EmbeddedResource,
    ImageContent,
    TextContent,
)
from conduit.protocol.resources import ResourceLink

# Deifning here to avoid circular imports
ContentBlock = (
    TextContent | ImageContent | AudioContent | EmbeddedResource | ResourceLink
)


class PromptArgument(BaseMetadata):
    """
    An argument that customizes a prompt template.

    Arguments let you adapt generic prompt expertise to your specific context.
    For example, a code review prompt might take 'language' and 'focus_areas'
    arguments to tailor the review style.
    """

    description: str | None = None
    """
    Human-readable description of what this argument controls.
    """

    required: bool | None = Field(default=None)
    """
    Whether this argument must be provided. Defaults to None.
    """


class Prompt(BaseMetadata):
    """
    A reusable prompt template that encapsulates domain expertise.

    Servers offer prompts as a way to share proven prompting strategies.
    Instead of crafting prompts from scratch, clients can leverage templates
    that domain experts have refined and tested.
    """

    description: str | None = None
    """
    Human-readable description of what this prompt does.
    """

    arguments: list[PromptArgument] | None = None
    """
    Arguments that customize this prompt for specific use cases.
    """

    metadata: dict[str, Any] | None = Field(default=None, alias="_meta")
    """
    Additional metadata about the prompt.
    """


class ListPromptsRequest(PaginatedRequest):
    """
    Request the catalog of prompts a server offers.

    Use this to discover what prompting expertise is available before
    deciding which prompts to use in your application.
    """

    method: Literal["prompts/list"] = "prompts/list"

    @classmethod
    def expected_result_type(cls) -> type["ListPromptsResult"]:
        return ListPromptsResult


class ListPromptsResult(PaginatedResult):
    """
    The server's catalog of available prompts.
    """

    prompts: list[Prompt]
    """
    List of available prompts.
    """


class PromptReference(BaseMetadata):
    """
    Reference to a prompt.
    """

    type: Literal["ref/prompt"] = "ref/prompt"


class PromptMessage(ProtocolModel):
    """
    One message in a multi-turn prompt conversation.

    Prompts can simulate entire conversations between user and assistant to
    establish context, provide examples, or guide specific workflows. Each
    message represents one turn in that conversation and can contain dynamic,
    server-sourced content like embedded resources.
    """

    role: Role
    content: ContentBlock


class GetPromptRequest(Request):
    """
    Request a specific prompt, customized with your arguments.

    The server takes your arguments and builds a complete, ready-to-use prompt.
    This might include static template text plus dynamic content like file
    contents, API responses, or other data the server can access.

    The result is a fully materialized prompt you can send directly to your LLM.
    """

    method: Literal["prompts/get"] = "prompts/get"
    name: str
    """
    Name of the prompt template to instantiate.
    """

    arguments: dict[str, str] | None = None
    """
    Arguments that customize the prompt for your specific use case.
    """

    @classmethod
    def expected_result_type(cls) -> type["GetPromptResult"]:
        return GetPromptResult


class GetPromptResult(Result):
    """
    A complete, ready-to-use prompt with all dynamic content resolved.

    The server has taken your template and arguments and built you a full prompt
    that might include embedded resources, media, or other content you couldn't
    access directly. Just present it to your user and pass it to your LLM.
    """

    description: str | None = None
    """
    What this prompt is designed to accomplish.
    """

    messages: list[PromptMessage]
    """
    The complete prompt messages, with all dynamic content embedded.
    """


class PromptListChangedNotification(Notification):
    """
    Server notification that its prompt catalog has changed.

    Servers send this when they add or remove some of their available prompts.
    Clients can respond by refreshing their prompt list to discover new
    capabilities or handle removed prompts gracefully.

    Note: Servers can send this anytime, even without a subscription request.
    """

    method: Literal["notifications/prompts/list_changed"] = (
        "notifications/prompts/list_changed"
    )

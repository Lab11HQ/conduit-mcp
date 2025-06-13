from typing import Annotated, Any

from pydantic import AnyUrl, Field, UrlConstraints, field_validator

from conduit.protocol.base import ProtocolModel, Role


class ResourceContents(ProtocolModel):
    """
    Base class for resource contents.
    """

    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]
    mime_type: str | None = Field(default=None, alias="mimeType")


class TextResourceContents(ResourceContents):
    """
    Resource contents represented as text (not binary text).
    """

    text: str
    """
    The text of the resource. Only set if the resource can be represented as text
    (not binary text).
    """


class BlobResourceContents(ResourceContents):
    """
    Resource contents represented as a binary blob.
    """

    blob: str
    """
    Base64-encoded string representing the binary data of the resource.
    """


class Annotations(ProtocolModel):
    """
    Display hints for client rendering.

    Guides how clients should use or present objects.
    """

    audience: list[Role] | Role | None = None
    """
    Target audience roles. Single role or list of roles.
    """

    priority: float | int | None = None
    """
    Priority level from 0 (lowest) to 1 (highest).
    """

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(cls, v: str | list[str] | Role | list[Role]):
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: float | int | None):
        if v is not None and not (0 <= v <= 1):
            raise ValueError("priority must be between 0 and 1")
        return v

    def to_protocol(self) -> dict[str, Any]:
        """Model dump to dict. Note 'audience' gets serialized to a list!"""
        return self.model_dump(exclude_none=True, mode="json")


class TextContent(ProtocolModel):
    """Text provided to or from an LLM."""

    type: str = Field(default="text", frozen=True)
    text: str
    """
    The text content of the message.
    """

    annotations: Annotations | None = None
    """
    Display hints for client use and rendering.
    """


class ImageContent(ProtocolModel):
    """
    An image provided to or from an LLM.

    Image is provided as base64-encoded data.
    """

    type: str = Field("image", frozen=True)
    mime_type: str = Field(alias="mimeType")
    data: str
    """
    The base64-encoded image data.
    """

    annotations: Annotations | None = None
    """
    Display hints for client use and rendering.
    """


class AudioContent(ProtocolModel):
    """
    Audio provided to or from an LLM.

    Audio is provided as base64-encoded data.
    """

    type: str = Field("audio", frozen=True)
    mime_type: str = Field(alias="mimeType")
    data: str
    """
    The base64-encoded audio data
    """

    annotations: Annotations | None = None
    """
    Display hints for client use and rendering.
    """


class EmbeddedResource(ProtocolModel):
    """
    The contents of a resource that is embedded in a prompt or tool call result.

    Client determines how to display the resource for the benefit of the LLM and/or
    user.
    """

    type: str = Field("resource", frozen=True)
    resource: TextResourceContents | BlobResourceContents
    annotations: Annotations | None = None
    """
    Display hints for client use and rendering.
    """


AnyContent = TextContent | ImageContent | AudioContent | EmbeddedResource

ContentList = list[AnyContent]

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from conduit.protocol.base import ProtocolModel, Role


class ResourceContents(ProtocolModel):
    """
    Base information for any resource content.

    Resources are data that servers can provide - files, database results, API
    responses, or any content identified by a URI. This base class captures the
    essential metadata that all resource content shares.
    """

    uri: str
    """
    The URI that identifies this specific resource.
    """

    mime_type: str | None = Field(default=None, alias="mimeType")
    """
    Content type of the resource, when known. Examples: "image/png", "audio/wav", etc.
    """

    metadata: dict[str, Any] | None = Field(default=None, alias="_meta")
    """
    Additional metadata about the resource.
    """


class TextResourceContents(ResourceContents):
    """
    Resource contents as readable text.

    Use this for files, API responses, database results, or any content
    that can be meaningfully displayed as text to users and LLMs.
    """

    text: str
    """
    The text content of the resource.
    """


class BlobResourceContents(ResourceContents):
    """
    Resource contents as binary data.

    Use this for images, documents, audio files, or any content that
    needs to be base64-encoded for transmission.
    """

    blob: str
    """
    Base64-encoded binary data.
    """


class Annotations(ProtocolModel):
    """
    Hints about how to handle content in prompts and responses.

    Helps clients decide what to show users versus what to send directly
    to the LLM, and how important different pieces of content are for
    accomplishing the task at hand.
    """

    audience: list[Role] | Role | None = None
    """
    Who this content is intended for: "user" (show in UI), "assistant" 
    (send to LLM), or both.
    """

    priority: float | int | None = None
    """
    How essential this content is for the task, from 0 (optional) to 1 (required).
    Helps clients handle resource loading failures or display constraints gracefully.
    """

    last_modified: str | None = Field(default=None, alias="lastModified")
    """
    The last modified time of the content, in ISO 8601 format.
    
    Must be a valid ISO 8601 formatted string (e.g., "2025-01-12T15:00:58Z").
    Examples: last activity timestamp in an open file, timestamp when the 
    resource was attached, etc.
    """

    @field_validator("audience", mode="before")
    @classmethod
    def validate_audience(
        cls, v: str | list[str] | Role | list[Role]
    ) -> list[str] | list[Role] | Role:
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: float | int | None) -> float | int | None:
        if v is not None and not (0 <= v <= 1):
            raise ValueError("priority must be between 0 and 1")
        return v

    @field_validator("last_modified")
    @classmethod
    def validate_last_modified(cls, v: str | None) -> str | None:
        if v is None:
            return v

        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return v
        except ValueError:
            raise ValueError(
                "last_modified must be a valid ISO 8601 formatted string "
                "(e.g., 'YYYY-MM-DD')"
            )


class TextContent(ProtocolModel):
    """
    Plain text content for prompts and responses.

    The most common content type - use this for instructions, examples,
    explanations, or any readable text you want to include in messages.
    """

    type: Literal["text"] = "text"
    text: str
    """The text content."""

    annotations: Annotations | None = None
    """Hints about how clients should handle this text."""

    metadata: dict[str, Any] | None = Field(default=None, alias="_meta")
    """
    Additional metadata about the text content.
    """


class ImageContent(ProtocolModel):
    """
    Image content for visual prompts and responses.

    Useful for prompts that need visual context - screenshots for debugging,
    diagrams for analysis, photos for description tasks, etc. Images are
    base64-encoded for transmission.
    """

    type: Literal["image"] = "image"

    data: str
    """
    Base64-encoded image data.
    """

    mime_type: str = Field(alias="mimeType")
    """
    Image format like 'image/png' or 'image/jpeg'.
    """

    annotations: Annotations | None = None
    """
    Hints about how clients should handle this image.
    """

    metadata: dict[str, Any] | None = Field(default=None, alias="_meta")
    """
    Additional metadata about the image content.
    """


class AudioContent(ProtocolModel):
    """
    Audio content for speech-enabled prompts and responses.

    Enable prompts that work with voice recordings, sound analysis,
    or audio generation tasks. Audio is base64-encoded for transmission.
    """

    type: Literal["audio"] = "audio"
    data: str
    """
    Base64-encoded audio data.
    """

    mime_type: str = Field(alias="mimeType")
    """
    Audio format like 'audio/wav' or 'audio/mp3'.
    """

    annotations: Annotations | None = None
    """
    Hints about how clients should handle this audio.
    """

    metadata: dict[str, Any] | None = Field(default=None, alias="_meta")
    """
    Additional metadata about the audio content.
    """


class EmbeddedResource(ProtocolModel):
    """
    Server-sourced content embedded directly into prompts or tool call results.

    This lets prompts and tool calls pull in real data—file contents,
    database results, images—rather than just being static templates.
    """

    type: Literal["resource"] = "resource"
    resource: TextResourceContents | BlobResourceContents
    """
    The actual resource content - text or binary data.
    """

    annotations: Annotations | None = None
    """
    Hints about how clients should handle this resource.
    """

    metadata: dict[str, Any] | None = Field(default=None, alias="_meta")
    """
    Additional metadata about the resource content.
    """

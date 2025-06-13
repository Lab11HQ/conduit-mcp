from typing import Annotated, Any, Literal

from pydantic import AnyUrl, Field, UrlConstraints

from conduit.protocol.base import (
    Notification,
    PaginatedRequest,
    PaginatedResult,
    ProtocolModel,
    Request,
    Result,
)
from conduit.protocol.content import (
    Annotations,
    BlobResourceContents,
    TextResourceContents,
)


class Resource(ProtocolModel):
    """
    A known resource the server can read from.
    """

    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]
    """
    Resource identifier (file path, URL, etc.).
    """

    name: str
    """
    Human-readable resource name. Client can display this to the user.
    """

    description: str | None = None
    """
    Optional resource description. Clients can use this to improve LLM understanding
    of the resource.
    """

    mime_type: str | None = Field(default=None, alias="mimeType")
    """
    MIME type of the resource content.
    """

    annotations: Annotations | None = None
    """
    Display hints for client use and rendering.
    """

    size_in_bytes: int | None = Field(default=None, alias="size")
    """
    Resource size in bytes. Used by Hosts to display file size and estimate token
    usage.
    """


class ResourceReference(ProtocolModel):
    """
    Reference to a resource.
    """

    type: Literal["ref/resource"] = "ref/resource"
    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]
    """
    URI or URI template of the resource.
    """


class ResourceTemplate(ProtocolModel):
    """
    A template for a set of resources that the server can read from.
    """

    uri_template: str = Field(alias="uriTemplate")
    """
    URI template following RFC 6570 specification (e.g., "file:///logs/{date}.log").
    Template variables are enclosed in braces and will be expanded when requesting
    the actual resource.
    """

    name: str
    """
    Human-readable name for the type of resource this template refers to. Clients can
    use this to populate UI elements.
    """

    description: str | None = None
    """
    Human-readable description of what this template is for. Clients can use this to
    improve LLM understanding of the available resources.
    """

    mime_type: str | None = Field(default=None, alias="mimeType")
    """
    MIME type of the resource content. Only include if all resources matching this
    template have the same type.
    """

    annotations: Annotations | None = None
    """
    Display hints for client use and rendering.
    """

    def to_protocol(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True, by_alias=True, mode="json")


class ListResourcesRequest(PaginatedRequest):
    """
    Request to list available resources with optional pagination.
    """

    method: Literal["resources/list"] = "resources/list"


class ListResourcesResult(PaginatedResult):
    """
    Response containing available resources and pagination info.
    """

    resources: list[Resource]
    """
    List of available resources.
    """


class ListResourceTemplatesRequest(PaginatedRequest):
    """
    Request to list available resource templates with optional pagination.
    """

    method: Literal["resources/templates/list"] = "resources/templates/list"


class ListResourceTemplatesResult(PaginatedResult):
    """
    Response containing available resource templates and pagination info.
    """

    resource_templates: list[ResourceTemplate] = Field(alias="resourceTemplates")
    """
    List of available resource templates.
    """


class ReadResourceRequest(Request):
    """
    Request to read a resource at a given URI.
    """

    method: Literal["resources/read"] = "resources/read"
    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]
    """
    URI of the resource to read.
    """


class ReadResourceResult(Result):
    """
    Response containing the content of a resource.
    """

    contents: list[TextResourceContents | BlobResourceContents]
    """
    The content of the resource.
    """


class ResourceListChangedNotification(Notification):
    method: Literal["notifications/resources/list_changed"] = (
        "notifications/resources/list_changed"
    )


class SubscribeRequest(Request):
    """
    Request to subscribe to resource update notifications for a given resource.
    """

    method: Literal["resources/subscribe"] = "resources/subscribe"
    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]


class UnsubscribeRequest(Request):
    """
    Request to unsubscribe from resource update notifications for a given resource.
    """

    method: Literal["resources/unsubscribe"] = "resources/unsubscribe"
    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]


class ResourceUpdatedNotification(Notification):
    """
    Notification that a resource has been updated.
    """

    method: Literal["notifications/resources/updated"] = (
        "notifications/resources/updated"
    )
    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]

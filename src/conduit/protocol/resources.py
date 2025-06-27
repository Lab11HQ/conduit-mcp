"""
Resource management for accessing server-side data.

Resources are how MCP servers expose their data to clients and LLMs - files,
database records, API endpoints, or any content that can be identified by URI.
The resource system provides discovery, templates for dynamic access, and
real-time change tracking.

## The Resource Workflow

1. **Discovery** - List available resources and templates to see what data the server
    provides
2. **Access** - Read specific resources or expand templates to get content
3. **Tracking** - Subscribe to resources that change over time for live updates

## Static vs Dynamic Resources

**Static resources** have fixed URIs that you discover through listing - individual
files, specific database records, or named API endpoints.

**Dynamic resources** use templates with variables like `file:///logs/{date}.log`,
letting you access large or infinite resource spaces without pre-listing every
possibility.

Resources provide the metadata (name, description, size), while the content
comes back as text or binary data when you read them. This separation keeps
discovery fast and lets applications decide what data they need.
"""

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
)
from conduit.protocol.common import EmptyResult
from conduit.protocol.content import (
    Annotations,
    BlobResourceContents,
    TextResourceContents,
)


class Resource(BaseMetadata):
    """
    A data source that the server can provide to clients and LLMs.

    Resources are how servers expose their data - files, database records,
    API endpoints, or any content that can be referenced by URI. Servers
    advertise what resources they have available, and clients can request
    the actual content when needed.

    Think of this as metadata about what's available, not the content itself.
    """

    uri: str
    """
    Unique identifier for this resource (file path, URL, database URI, etc.).
    """

    description: str | None = None
    """
    What this resource contains or represents. Helps LLMs understand
    when and how to use this resource effectively.
    """

    mime_type: str | None = Field(default=None, alias="mimeType")
    """
    Content type, when known (text/plain, image/png, etc.).
    """

    annotations: Annotations | None = None
    """
    Hints about how clients should handle this resource.
    """

    size_in_bytes: int | None = Field(default=None, alias="size")
    """
    Raw content size in bytes. Helps clients estimate context usage
    and display file sizes to users.
    """

    metadata: dict[str, Any] | None = Field(default=None, alias="_meta")
    """
    Additional metadata about the resource.
    """


class ResourceLink(Resource):
    """
    A resource the server can read. Included in a prompt or tool call result.

    Note: resource links returned by tools are not guaranteed to appear in the
    results of `resources/list` requests.
    """

    type: Literal["resource_link"] = "resource_link"
    """
    A link to a resource.
    """


class ResourceTemplateReference(ProtocolModel):
    """
    Reference to a resource.
    """

    type: Literal["ref/resource"] = "ref/resource"
    uri: str
    """
    URI or URI template of the resource.
    """


class ResourceTemplate(BaseMetadata):
    """
    A pattern for generating multiple related resources dynamically.

    Instead of listing every possible resource individually, servers can offer
    templates that clients expand with specific values. For example, a template
    like "file:///logs/{date}.log" lets clients access any date's log file
    without the server pre-listing every possible date.

    This enables access to large or infinite resource spaces efficiently.
    """

    uri_template: str = Field(alias="uriTemplate")
    """
    URI pattern following RFC 6570 (e.g., "file:///logs/{date}.log").
    Clients substitute values for variables in braces to create specific URIs.
    """

    description: str | None = None
    """
    What resources this template provides access to. Helps LLMs understand
    when and how to use this template effectively.
    """

    mime_type: str | None = Field(default=None, alias="mimeType")
    """
    Content type for all resources matching this template, when consistent
    across the entire pattern.
    """

    annotations: Annotations | None = None
    """
    Hints about how clients should handle resources from this template.
    """

    metadata: dict[str, Any] | None = Field(default=None, alias="_meta")


class ListResourcesRequest(PaginatedRequest):
    """
    Discover what data sources the server can provide.

    Use this to build catalogs, populate UI dropdowns, or let LLMs know
    what information they can request from this server.
    """

    method: Literal["resources/list"] = "resources/list"

    @classmethod
    def expected_result_type(cls) -> type["ListResourcesResult"]:
        return ListResourcesResult


class ListResourcesResult(PaginatedResult):
    """
    The server's catalog of available data sources.
    """

    resources: list[Resource]
    """
    Individual resources the server can provide.
    """


class ListResourceTemplatesRequest(PaginatedRequest):
    """
    Discover what dynamic resource patterns the server offers.

    Templates let you access large resource spaces efficiently - like
    requesting any date's logs or any user's profile without the server
    pre-listing every possibility.
    """

    method: Literal["resources/templates/list"] = "resources/templates/list"

    @classmethod
    def expected_result_type(cls) -> type["ListResourceTemplatesResult"]:
        return ListResourceTemplatesResult


class ListResourceTemplatesResult(PaginatedResult):
    """
    The server's catalog of dynamic resource patterns.
    """

    resource_templates: list[ResourceTemplate] = Field(alias="resourceTemplates")
    """
    Template patterns you can expand to access specific resources.
    """


class ReadResourceRequest(Request):
    """
    Request the content of a specific resource.

    This is where you move from discovery to action - taking a URI from
    the resource catalog or expanding a template and getting the real data
    to use in prompts or analysis.
    """

    method: Literal["resources/read"] = "resources/read"
    uri: str
    """
    URI of the resource to fetch content from.
    """

    @classmethod
    def expected_result_type(cls) -> type["ReadResourceResult"]:
        return ReadResourceResult


class ReadResourceResult(Result):
    """
    The content of a resource, ready to use.

    Resources can contain multiple pieces of content (like a directory
    with multiple files), so this always returns a list even for single items.
    """

    contents: list[TextResourceContents | BlobResourceContents]
    """
    The resource content - text, binary data, or both.
    """


class ResourceListChangedNotification(Notification):
    """
    Server notification that its resource catalog has changed.

    Servers send this when they add or remove available resources. Clients can
    respond by refreshing their resource list to discover new data sources or
    handle removed ones gracefully.

    Note: Servers can send this anytime, even without a subscription request.
    """

    method: Literal["notifications/resources/list_changed"] = (
        "notifications/resources/list_changed"
    )


class SubscribeRequest(Request):
    """
    Watch a specific resource for changes.

    Use this when your application needs to stay current with dynamic data -
    log files that grow, databases that update, or any resource that changes
    over time. The server will notify you when the content changes.

    Note: Does not expect a response.
    """

    method: Literal["resources/subscribe"] = "resources/subscribe"
    uri: str
    """
    URI of the resource to monitor for changes.
    """

    @classmethod
    def expected_result_type(cls) -> type[EmptyResult]:
        return EmptyResult


class UnsubscribeRequest(Request):
    """
    Stop watching a resource for changes.

    Send this when you no longer need updates about a resource, typically
    when cleaning up subscriptions or when users navigate away from data
    that's no longer relevant.

    Note: Does not expect a response.
    """

    method: Literal["resources/unsubscribe"] = "resources/unsubscribe"
    uri: str
    """
    URI of the resource to stop monitoring.
    """

    @classmethod
    def expected_result_type(cls) -> type[EmptyResult]:
        return EmptyResult


class ResourceUpdatedNotification(Notification):
    """
    Server notification that a watched resource has changed.

    Signals that you should re-read the resource to get current data.
    The URI might be more specific than what you originally subscribed to -
    for example, subscribing to a directory might generate notifications
    for individual files within it.

    Note: Servers should only send this if a client has explicitly
    subscribed to a resource.
    """

    method: Literal["notifications/resources/updated"] = (
        "notifications/resources/updated"
    )
    uri: str
    """
    URI of the resource that changed.
    """

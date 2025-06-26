import re
from typing import Awaitable, Callable

from conduit.protocol.common import EmptyResult
from conduit.protocol.resources import (
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    ReadResourceRequest,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    SubscribeRequest,
    UnsubscribeRequest,
)


class ResourceManager:
    def __init__(self):
        # Static resources
        self.registered: dict[str, Resource] = {}
        self.handlers: dict[
            str, Callable[[ReadResourceRequest], Awaitable[ReadResourceResult]]
        ] = {}

        # Templates (dynamic resources with URI patterns)
        self.templates: dict[str, ResourceTemplate] = {}
        self.template_handlers: dict[
            str, Callable[[ReadResourceRequest], Awaitable[ReadResourceResult]]
        ] = {}

        # Subscriptions and callbacks
        self.subscriptions: set[str] = set()
        self.on_subscribe: Callable[[str], Awaitable[None]] | None = None
        self.on_unsubscribe: Callable[[str], Awaitable[None]] | None = None

    def register_resource(self, resource: Resource, handler: Callable) -> None:
        """Register a static resource with its handler."""
        self.registered[resource.uri] = resource
        self.handlers[resource.uri] = handler

    def register_template(self, template: ResourceTemplate, handler: Callable) -> None:
        """Register a resource template with its handler."""
        self.templates[template.uri_template] = template
        self.template_handlers[template.uri_template] = handler

    async def handle_list_resources(
        self, request: ListResourcesRequest
    ) -> ListResourcesResult:
        """Handle list resources request with pagination support.

        Ignores pagination parameters for now. Can handle cursor, nextCursor,
        filtering, etc.
        """
        # Can handle cursor, nextCursor, filtering, etc.
        return ListResourcesResult(resources=list(self.registered.values()))

    async def handle_list_templates(
        self, request: ListResourceTemplatesRequest
    ) -> ListResourceTemplatesResult:
        """Handle list templates request with pagination support.

        Ignores pagination parameters for now. Can handle cursor, nextCursor,
        filtering, etc.
        """
        return ListResourceTemplatesResult(
            resource_templates=list(self.templates.values())
        )

    async def handle_read(self, request: ReadResourceRequest) -> ReadResourceResult:
        """Handle a read resource request. Raises KeyError if resource not found."""
        uri = str(request.uri)

        # Try static resources first
        if uri in self.handlers:
            return await self.handlers[uri](request)

        # Try template patterns
        for template_pattern, handler in self.template_handlers.items():
            if self._matches_template(template_pattern, uri):
                return await handler(request)

        # Not found - let session handle as protocol error
        raise KeyError(f"Unknown resource: {uri}")

    async def handle_subscribe(self, request: SubscribeRequest) -> EmptyResult:
        """Subscribe to a resource."""
        uri = str(request.uri)
        if uri not in self.registered:
            # Check if any templates match
            template_found = any(
                self._matches_template(uri, template)
                for template in self.templates.keys()
            )
            if not template_found:
                raise KeyError(f"Cannot subscribe to unknown resource: {uri}")

        self.subscriptions.add(uri)
        if self.on_subscribe:
            await self.on_subscribe(uri)

        return EmptyResult()

    async def handle_unsubscribe(self, request: UnsubscribeRequest) -> EmptyResult:
        """Handle unsubscription request. Raises KeyError if not subscribed."""
        uri = str(request.uri)

        # Validate we're actually subscribed to this resource
        if uri not in self.subscriptions:
            raise KeyError(f"Not subscribed to resource: {uri}")

        # Remove subscription and call callback
        self.subscriptions.remove(uri)  # Can use remove() now since we validated
        if self.on_unsubscribe:
            await self.on_unsubscribe(uri)

        return EmptyResult()

    def _matches_template(self, uri: str, template: str) -> bool:
        """Check if a URI matches a URI template pattern.

        Supports basic RFC 6570 variable substitution like {var}.
        Returns True if the URI could have been generated from this template.
        """
        # Convert template to regex pattern
        # Replace {variable} with regex group that matches non-slash characters
        pattern = re.escape(template)
        pattern = re.sub(r"\\{[^}]+\\}", r"([^/]+)", pattern)
        pattern = f"^{pattern}$"

        return bool(re.match(pattern, uri))

    def _extract_template_variables(self, uri: str, template: str) -> dict[str, str]:
        """Extract variable values from a URI using a template.

        Returns a dict mapping variable names to their values.
        """
        # Find variable names in template
        var_names = re.findall(r"{([^}]+)}", template)

        # Convert template to regex with named groups
        pattern = re.escape(template)
        for var_name in var_names:
            pattern = pattern.replace(f"\\{{{var_name}\\}}", f"(?P<{var_name}>[^/]+)")
        pattern = f"^{pattern}$"

        match = re.match(pattern, uri)
        if match:
            return match.groupdict()
        return {}

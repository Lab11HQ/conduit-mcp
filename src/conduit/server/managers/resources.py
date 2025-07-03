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
        """Register a static resource with its handler function.

        Your handler should return ReadResourceResult with the resource content.
        Handler exceptions become INTERNAL_ERROR responses, so consider handling
        expected failures gracefully within your handler by returning appropriate
        content or error messages in the resource text.

        Args:
            resource: Resource definition with URI, description, etc.
            handler: Async function that processes read requests. Should return
                ReadResourceResult with resource contents.
        """
        self.registered[resource.uri] = resource
        self.handlers[resource.uri] = handler

    def register_template(self, template: ResourceTemplate, handler: Callable) -> None:
        """Register a resource template with its handler function.

        Your handler receives requests with expanded URIs (e.g.,
        'file:///logs/2024-01-15.log' from template 'file:///logs/{date}.log').
        Handler exceptions become INTERNAL_ERROR responses, so consider handling
        expected failures gracefully within your handler.

        Args:
            template: Resource template with URI pattern, description, etc.
            handler: Async function that processes read requests for matching URIs
                generated from the template. Should return ReadResourceResult with
                resource contents.
        """
        self.templates[template.uri_template] = template
        self.template_handlers[template.uri_template] = handler

    async def handle_list_resources(
        self, request: ListResourcesRequest
    ) -> ListResourcesResult:
        """List all registered static resources.

        Ignores pagination parameters for now - returns all resources.
        Future versions can handle cursor, limit, and filtering.

        Args:
            request: List resources request with optional pagination.

        Returns:
            ListResourcesResult: All registered static resources.
        """
        return ListResourcesResult(resources=list(self.registered.values()))

    async def handle_read(self, request: ReadResourceRequest) -> ReadResourceResult:
        """Read a resource by URI, checking static resources then templates.

        Tries static resources first, then attempts template pattern matching.
        Handler exceptions bubble up to the session for protocol error conversion.

        Args:
            request: Read resource request with URI.

        Returns:
            ReadResourceResult: Resource content from the handler.

        Raises:
            KeyError: If the URI matches no static resource or template pattern.
            Exception: Any exception from the resource handler.
        """
        uri = request.uri

        # Try static resources first
        if uri in self.handlers:
            try:
                return await self.handlers[uri](request)
            except Exception:
                raise

        # Try template patterns
        for template_pattern, handler in self.template_handlers.items():
            if self._matches_template(uri=uri, template=template_pattern):
                try:
                    return await handler(request)
                except Exception:
                    raise

        # Not found - let session handle as protocol error
        raise KeyError(f"Unknown resource: {uri}")

    async def handle_list_templates(
        self, request: ListResourceTemplatesRequest
    ) -> ListResourceTemplatesResult:
        """List all registered resource templates.

        Templates enable dynamic resource access with URI patterns like
        'file:///logs/{date}.log'. Ignores pagination parameters for now.

        Args:
            request: List templates request with optional pagination.

        Returns:
            ListResourceTemplatesResult: All registered resource templates.
        """
        return ListResourceTemplatesResult(
            resource_templates=list(self.templates.values())
        )

    async def handle_subscribe(self, request: SubscribeRequest) -> EmptyResult:
        """Subscribe to resource change notifications.

        Validates the resource exists (static or template match), records the
        subscription, and calls the on_subscribe callback. Callback failures are
        logged but don't fail the subscription since it's recorded and may work with
        other update mechanisms.

        Args:
            request: Subscribe request with resource URI.

        Returns:
            EmptyResult: Subscription recorded successfully.

        Raises:
            KeyError: If the URI matches no static resource or template pattern.
        """
        uri = request.uri
        if uri not in self.registered:
            template_found = any(
                self._matches_template(uri=uri, template=template)
                for template in self.templates.keys()
            )
            if not template_found:
                raise KeyError(f"Cannot subscribe to unknown resource: {uri}")

        self.subscriptions.add(uri)
        if self.on_subscribe:
            try:
                await self.on_subscribe(uri)
            except Exception as e:
                print(f"Error in on_subscribe callback: {uri}: {e}")

        return EmptyResult()

    async def handle_unsubscribe(self, request: UnsubscribeRequest) -> EmptyResult:
        """Unsubscribe from resource change notifications.

        Validates the subscription exists, removes it, and calls the on_unsubscribe
        callback. Callback failures are logged but don't fail the operation since the
        subscription is already removed.

        Args:
            request: Unsubscribe request with resource URI.

        Returns:
            EmptyResult: Unsubscription completed successfully.

        Raises:
            KeyError: If not currently subscribed to the resource.
        """
        uri = request.uri

        # Validate we're actually subscribed to this resource
        if uri not in self.subscriptions:
            raise KeyError(f"Not subscribed to resource: {uri}")

        # Remove subscription and call callback
        self.subscriptions.remove(uri)  # Can use remove() now since we validated
        if self.on_unsubscribe:
            try:
                await self.on_unsubscribe(uri)
            except Exception as e:
                print(f"Error in on_unsubscribe callback: {uri}: {e}")

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

    # def _extract_template_variables(self, uri: str, template: str) -> dict[str, str]:
    #     """Extract variable values from a URI using a template.

    #     Returns a dict mapping variable names to their values.
    #     """
    #     # Find variable names in template
    #     var_names = re.findall(r"{([^}]+)}", template)

    #     # Convert template to regex with named groups
    #     pattern = re.escape(template)
    #     for var_name in var_names:
    #         pattern = pattern.replace(f"\\{{{var_name}\\}}", f"(?P<{var_name}>[^/]+)")
    #     pattern = f"^{pattern}$"

    #     match = re.match(pattern, uri)
    #     if match:
    #         return match.groupdict()
    #     return {}

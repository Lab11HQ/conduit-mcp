"""Client-aware resource manager for multi-client server sessions."""

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
from conduit.server.client_manager import ClientManager

# Type aliases for client-aware handlers
ClientAwareResourceHandler = Callable[
    [str, ReadResourceRequest], Awaitable[ReadResourceResult]
]
ClientAwareSubscriptionCallback = Callable[
    [str, str], Awaitable[None]
]  # (client_id, uri)


class ResourceManager:
    """Client-aware resource manager for multi-client server sessions.

    Manages global resource registration with client-specific subscriptions.
    Resources are registered once but subscriptions are tracked per-client,
    enabling targeted notifications when resources change.
    """

    def __init__(self, client_manager: ClientManager):
        self.client_manager = client_manager

        # Static resources (global)
        self.registered_resources: dict[str, Resource] = {}
        self.handlers: dict[str, ClientAwareResourceHandler] = {}

        # Templates (global, dynamic resources with URI patterns)
        self.registered_templates: dict[str, ResourceTemplate] = {}
        self.template_handlers: dict[str, ClientAwareResourceHandler] = {}

        # Callbacks now receive client context
        self._on_subscribe: ClientAwareSubscriptionCallback | None = None
        self._on_unsubscribe: ClientAwareSubscriptionCallback | None = None

    def register(
        self,
        resource_or_template: Resource | ResourceTemplate,
        handler: ClientAwareResourceHandler,
    ) -> None:
        """Register a resource or template with its client-aware handler function.

        Resources are registered globally but handlers receive client context
        during execution. This allows resources to behave differently per client
        for access control, personalization, or logging.

        Your handler should return ReadResourceResult with the resource content.
        Handler exceptions become INTERNAL_ERROR responses, so consider handling
        expected failures gracefully within your handler by returning appropriate
        content or error messages in the resource text.

        Args:
            resource_or_template: Resource definition (static) or ResourceTemplate
                (dynamic with URI patterns) to register.
            handler: Async function that processes read requests with client context.
                Should return ReadResourceResult with resource contents.
        """
        if isinstance(resource_or_template, Resource):
            self.registered_resources[resource_or_template.uri] = resource_or_template
            self.handlers[resource_or_template.uri] = handler
        elif isinstance(resource_or_template, ResourceTemplate):
            self.registered_templates[resource_or_template.uri_template] = (
                resource_or_template
            )
            self.template_handlers[resource_or_template.uri_template] = handler

    def on_subscribe(self, callback: ClientAwareSubscriptionCallback) -> None:
        """Register callback for resource subscription events.

        Args:
            callback: Async function called when a client subscribes to a resource.
                Receives (client_id, resource_uri) as arguments.
        """
        self._on_subscribe = callback

    def on_unsubscribe(self, callback: ClientAwareSubscriptionCallback) -> None:
        """Register callback for resource unsubscription events.

        Args:
            callback: Async function called when a client unsubscribes from a resource.
                Receives (client_id, resource_uri) as arguments.
        """
        self._on_unsubscribe = callback

    async def handle_list_resources(
        self, client_id: str, request: ListResourcesRequest
    ) -> ListResourcesResult:
        """List all registered static resources for specific client.

        Returns all registered resources. Could be extended to filter resources
        based on client permissions or capabilities.

        Args:
            client_id: ID of the client requesting resources
            request: List resources request with optional pagination

        Returns:
            ListResourcesResult: All registered static resources
        """
        # For now, all clients see all resources
        # Could add client-specific filtering here
        return ListResourcesResult(resources=list(self.registered_resources.values()))

    async def handle_list_templates(
        self, client_id: str, request: ListResourceTemplatesRequest
    ) -> ListResourceTemplatesResult:
        """List all registered resource templates for specific client.

        Templates enable dynamic resource access with URI patterns like
        'file:///logs/{date}.log'. Could be extended for client-specific templates.

        Args:
            client_id: ID of the client requesting templates
            request: List templates request with optional pagination

        Returns:
            ListResourceTemplatesResult: All registered resource templates
        """
        return ListResourceTemplatesResult(
            resource_templates=list(self.registered_templates.values())
        )

    async def handle_read(
        self, client_id: str, request: ReadResourceRequest
    ) -> ReadResourceResult:
        """Read a resource by URI for specific client.

        Tries static resources first, then attempts template pattern matching.
        Handler exceptions bubble up to the session for protocol error conversion.

        Args:
            client_id: ID of the client reading the resource
            request: Read resource request with URI

        Returns:
            ReadResourceResult: Resource content from the handler

        Raises:
            KeyError: If the URI matches no static resource or template pattern
            Exception: Any exception from the resource handler
        """
        uri = request.uri

        # Try static resources first
        if uri in self.handlers:
            try:
                return await self.handlers[uri](client_id, request)
            except Exception:
                raise

        # Try template patterns
        for template_pattern, handler in self.template_handlers.items():
            if self._matches_template(uri=uri, template=template_pattern):
                try:
                    return await handler(client_id, request)
                except Exception:
                    raise

        # Not found - let session handle as protocol error
        raise KeyError(f"Unknown resource: {uri}")

    async def handle_subscribe(
        self, client_id: str, request: SubscribeRequest
    ) -> EmptyResult:
        """Subscribe client to resource change notifications.

        Validates the resource exists (static or template match), records the
        client-specific subscription, and calls the on_subscribe callback.

        Args:
            client_id: ID of the client subscribing
            request: Subscribe request with resource URI

        Returns:
            EmptyResult: Subscription recorded successfully

        Raises:
            KeyError: If the URI matches no static resource or template pattern
        """
        uri = request.uri

        # Validate resource exists
        if uri not in self.registered_resources:
            template_found = any(
                self._matches_template(uri=uri, template=template)
                for template in self.registered_templates.keys()
            )
            if not template_found:
                raise KeyError(f"Cannot subscribe to unknown resource: {uri}")

        # Get client context (should exist from initialization)
        context = self.client_manager.get_client(client_id)
        if context:
            context.subscriptions.add(uri)

        # Call callback with client context
        if self._on_subscribe:
            try:
                await self._on_subscribe(client_id, uri)
            except Exception as e:
                print(f"Error in on_subscribe callback for {client_id}: {uri}: {e}")

        return EmptyResult()

    async def handle_unsubscribe(
        self, client_id: str, request: UnsubscribeRequest
    ) -> EmptyResult:
        """Unsubscribe client from resource change notifications.

        Validates the client subscription exists, removes it, and calls the
        on_unsubscribe callback.

        Args:
            client_id: ID of the client unsubscribing
            request: Unsubscribe request with resource URI

        Returns:
            EmptyResult: Unsubscription completed successfully

        Raises:
            KeyError: If client not currently subscribed to the resource
        """
        uri = request.uri

        # Get client context (should exist from initialization)
        context = self.client_manager.get_client(client_id)
        if not context or uri not in context.subscriptions:
            raise KeyError(f"Client not subscribed to resource: {uri}")

        # Remove subscription for this client
        context.subscriptions.remove(uri)

        # Call callback with client context
        if self._on_unsubscribe:
            try:
                await self._on_unsubscribe(client_id, uri)
            except Exception as e:
                print(f"Error in on_unsubscribe callback for {client_id}: {uri}: {e}")

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

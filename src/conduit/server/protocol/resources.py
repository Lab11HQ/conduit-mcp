"""Client-aware resource manager for multi-client server sessions."""

import re
from copy import deepcopy
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

# Type aliases for client-aware handlers
ClientAwareResourceHandler = Callable[
    [str, ReadResourceRequest], Awaitable[ReadResourceResult]
]
ClientAwareSubscriptionCallback = Callable[
    [str, str], Awaitable[None]
]  # (client_id, uri)


class ResourceManager:
    """Client-aware resource manager for multi-client server sessions.

    Manages global and client-specific resource registration with
    client-specific subscriptions tracked internally.
    """

    def __init__(self):
        # Global resources (shared across all clients)
        self.global_resources: dict[str, Resource] = {}
        self.global_handlers: dict[str, ClientAwareResourceHandler] = {}

        # Global templates (shared across all clients)
        self.global_templates: dict[str, ResourceTemplate] = {}
        self.global_template_handlers: dict[str, ClientAwareResourceHandler] = {}

        # Client-specific resources
        self.client_resources: dict[
            str, dict[str, Resource]
        ] = {}  # client_id -> {uri: resource}
        self.client_handlers: dict[str, dict[str, ClientAwareResourceHandler]] = {}

        # Client-specific templates
        self.client_templates: dict[str, dict[str, ResourceTemplate]] = {}
        self.client_template_handlers: dict[
            str, dict[str, ClientAwareResourceHandler]
        ] = {}

        # Client subscriptions (what we manage FOR each client)
        self._client_subscriptions: dict[str, set[str]] = {}  # client_id -> {uri, ...}

        # Direct callback assignment
        self.subscribe_handler: ClientAwareSubscriptionCallback | None = None
        self.unsubscribe_handler: ClientAwareSubscriptionCallback | None = None

    # ===============================
    # Global resource management
    # ===============================

    def add_resource(
        self,
        resource: Resource,
        handler: ClientAwareResourceHandler,
    ) -> None:
        """Add a global resource with its client-aware handler function.

        Your handler should return ReadResourceResult with the resource content.
        Handler exceptions bubble up to the session for protocol error conversion.

        Args:
            resource: Resource definition with URI and metadata.
            handler: Async function that processes read requests with client context.
                Should return ReadResourceResult with resource contents.
        """
        self.global_resources[resource.uri] = resource
        self.global_handlers[resource.uri] = handler

    def add_template(
        self,
        template: ResourceTemplate,
        handler: ClientAwareResourceHandler,
    ) -> None:
        """Add a global resource template with its client-aware handler function.

        Templates enable dynamic resource access with URI patterns like
        'file:///logs/{date}.log'. Available to all clients.

        Args:
            template: ResourceTemplate definition with URI pattern and metadata.
            handler: Async function that processes read requests with client context.
        """
        self.global_templates[template.uri_template] = template
        self.global_template_handlers[template.uri_template] = handler

    def get_resources(self) -> dict[str, Resource]:
        """Get all global resources."""
        return deepcopy(self.global_resources)

    def get_templates(self) -> dict[str, ResourceTemplate]:
        """Get all global resource templates."""
        return deepcopy(self.global_templates)

    def remove_resource(self, uri: str) -> None:
        """Remove a global resource by URI."""
        self.global_resources.pop(uri, None)
        self.global_handlers.pop(uri, None)

    def remove_template(self, uri_template: str) -> None:
        """Remove a global resource template by URI template."""
        self.global_templates.pop(uri_template, None)
        self.global_template_handlers.pop(uri_template, None)

    def clear_resources(self) -> None:
        """Remove all global resources and their handlers."""
        self.global_resources.clear()
        self.global_handlers.clear()

    def clear_templates(self) -> None:
        """Remove all global resource templates and their handlers."""
        self.global_templates.clear()
        self.global_template_handlers.clear()

    # ===============================
    # Client-specific resource management
    # ===============================

    def add_client_resource(
        self,
        client_id: str,
        resource: Resource,
        handler: ClientAwareResourceHandler,
    ) -> None:
        """Add a resource specific to a client.

        Client-specific resources are only available to the specified client and can
        override global resources with the same URI for that client.

        Args:
            client_id: ID of the client this resource is specific to.
            resource: Resource definition with URI and metadata.
            handler: Async function that processes read requests with client context.
        """
        if client_id not in self.client_resources:
            self.client_resources[client_id] = {}
            self.client_handlers[client_id] = {}

        self.client_resources[client_id][resource.uri] = resource
        self.client_handlers[client_id][resource.uri] = handler

    def add_client_template(
        self,
        client_id: str,
        template: ResourceTemplate,
        handler: ClientAwareResourceHandler,
    ) -> None:
        """Add a resource template specific to a client.

        Client-specific templates are only available to the specified client and can
        override global templates with the same URI pattern for that client.

        Args:
            client_id: ID of the client this template is specific to.
            template: ResourceTemplate definition with URI pattern and metadata.
            handler: Async function that processes read requests with client context.
        """
        if client_id not in self.client_templates:
            self.client_templates[client_id] = {}
            self.client_template_handlers[client_id] = {}

        self.client_templates[client_id][template.uri_template] = template
        self.client_template_handlers[client_id][template.uri_template] = handler

    def get_client_resources(self, client_id: str) -> dict[str, Resource]:
        """Get all resources available to a specific client.

        Returns global resources plus any client-specific resources. Client-specific
        resources override global resources with the same URI.

        Args:
            client_id: ID of the client to get resources for.

        Returns:
            Dictionary mapping URIs to Resource objects for this client.
        """
        # Start with global resources
        resources = deepcopy(self.global_resources)

        # Add client-specific resources, with override logging
        if client_id in self.client_resources:
            for uri, resource in self.client_resources[client_id].items():
                if uri in resources:
                    print(f"Client {client_id} overriding global resource '{uri}'")
                resources[uri] = resource

        return resources

    def get_client_templates(self, client_id: str) -> dict[str, ResourceTemplate]:
        """Get all resource templates available to a specific client.

        Returns global templates plus any client-specific templates. Client-specific
        templates override global templates with the same URI pattern.

        Args:
            client_id: ID of the client to get templates for.

        Returns:
            Dictionary mapping URI patterns to ResourceTemplate objects for this client.
        """
        # Start with global templates
        templates = deepcopy(self.global_templates)

        # Add client-specific templates, with override logging
        if client_id in self.client_templates:
            for pattern, template in self.client_templates[client_id].items():
                if pattern in templates:
                    print(f"Client {client_id} overriding global template '{pattern}'")
                templates[pattern] = template

        return templates

    def remove_client_resource(self, client_id: str, uri: str) -> None:
        """Remove a client-specific resource by URI."""
        if client_id in self.client_resources:
            self.client_resources[client_id].pop(uri, None)
            self.client_handlers[client_id].pop(uri, None)

    def remove_client_template(self, client_id: str, uri_template: str) -> None:
        """Remove a client-specific resource template by URI pattern."""
        if client_id in self.client_templates:
            self.client_templates[client_id].pop(uri_template, None)
            self.client_template_handlers[client_id].pop(uri_template, None)

    def cleanup_client(self, client_id: str) -> None:
        """Remove all resources, templates, and subscriptions for a client."""
        self.client_resources.pop(client_id, None)
        self.client_handlers.pop(client_id, None)
        self.client_templates.pop(client_id, None)
        self.client_template_handlers.pop(client_id, None)
        self._client_subscriptions.pop(client_id, None)

    # ===============================
    # Protocol handlers
    # ===============================

    async def handle_list_resources(
        self, client_id: str, request: ListResourcesRequest
    ) -> ListResourcesResult:
        """List all resources available to a specific client."""
        resources = self.get_client_resources(client_id)
        return ListResourcesResult(resources=list(resources.values()))

    async def handle_list_templates(
        self, client_id: str, request: ListResourceTemplatesRequest
    ) -> ListResourceTemplatesResult:
        """List all resource templates available to a specific client."""
        templates = self.get_client_templates(client_id)
        return ListResourceTemplatesResult(resource_templates=list(templates.values()))

    async def handle_read(
        self, client_id: str, request: ReadResourceRequest
    ) -> ReadResourceResult:
        """Read a resource by URI for specific client.

        Client-specific handlers override global handlers for the same URI.

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

        # Try static resources first - check client-specific then global
        if client_id in self.client_handlers and uri in self.client_handlers[client_id]:
            return await self.client_handlers[client_id][uri](client_id, request)
        elif uri in self.global_handlers:
            return await self.global_handlers[uri](client_id, request)

        # Try template patterns - check client-specific then global
        if client_id in self.client_template_handlers:
            for template_pattern, handler in self.client_template_handlers[
                client_id
            ].items():
                if self._matches_template(uri=uri, template=template_pattern):
                    return await handler(client_id, request)

        # Check global templates
        for template_pattern, handler in self.global_template_handlers.items():
            if self._matches_template(uri=uri, template=template_pattern):
                return await handler(client_id, request)

        # Not found
        raise KeyError(f"Unknown resource: {uri}")

    async def handle_subscribe(
        self, client_id: str, request: SubscribeRequest
    ) -> EmptyResult:
        """Subscribe client to resource change notifications.

        Args:
            client_id: ID of the client subscribing
            request: Subscribe request with resource URI

        Returns:
            EmptyResult: Subscription recorded successfully

        Raises:
            KeyError: If the URI matches no static resource or template pattern
        """
        resource_exists = False
        uri = request.uri

        client_resources = self.get_client_resources(client_id)
        if uri in client_resources:
            resource_exists = True  # static resource
        else:
            # template resource
            client_templates = self.get_client_templates(client_id)
            for template_pattern in client_templates.keys():
                if self._matches_template(uri=uri, template=template_pattern):
                    resource_exists = True
                    break

        if not resource_exists:
            raise KeyError(f"Cannot subscribe to unknown resource: {uri}")

        # Record the subscription
        client_subscriptions = self._client_subscriptions.setdefault(client_id, set())
        client_subscriptions.add(uri)

        # Notify via callback if configured
        if self.subscribe_handler:
            try:
                await self.subscribe_handler(client_id, uri)
            except Exception as e:
                print(f"Error in subscribe handler for {client_id}: {uri}: {e}")

        return EmptyResult()

    async def handle_unsubscribe(
        self, client_id: str, request: UnsubscribeRequest
    ) -> EmptyResult:
        """Unsubscribe client from resource change notifications.

        Args:
            client_id: ID of the client unsubscribing
            request: Unsubscribe request with resource URI

        Returns:
            EmptyResult: Unsubscription completed successfully

        Raises:
            KeyError: If client not currently subscribed to the resource
        """
        uri = request.uri
        client_subscriptions = self._client_subscriptions.get(client_id, set())

        # Check if client is subscribed
        if uri not in client_subscriptions:
            raise KeyError(f"Client not subscribed to resource: {uri}")

        # Remove the subscription
        self._client_subscriptions[client_id].remove(uri)

        # Notify via callback if configured
        if self.unsubscribe_handler:
            try:
                await self.unsubscribe_handler(client_id, uri)
            except Exception as e:
                print(f"Error in unsubscribe handler for {client_id}: {uri}: {e}")

        return EmptyResult()

    def _matches_template(self, uri: str, template: str) -> bool:
        """Checks if a URI matches a URI template pattern."""
        # Convert template to regex pattern
        # Replace {variable} with regex group that matches non-slash characters
        pattern = re.escape(template)
        pattern = re.sub(r"\\{[^}]+\\}", r"([^/]+)", pattern)
        pattern = f"^{pattern}$"

        return bool(re.match(pattern, uri))

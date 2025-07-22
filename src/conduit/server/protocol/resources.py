"""Client-aware resource manager for multi-client server sessions."""

import logging
import re
from copy import deepcopy
from typing import TYPE_CHECKING, Awaitable, Callable

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

if TYPE_CHECKING:
    from conduit.server.request_context import RequestContext


ResourceHandler = Callable[
    ["RequestContext", ReadResourceRequest], Awaitable[ReadResourceResult]
]
SubscriptionCallback = Callable[[str, str], Awaitable[None]]  # (client_id, uri)


class ResourceManager:
    """Manages protocol resource registration and execution for a server.

    Controls which resources are available to MCP clients and how they're executed.
    """

    def __init__(self):
        self.global_resources: dict[str, Resource] = {}
        self.global_handlers: dict[str, ResourceHandler] = {}

        self.global_templates: dict[str, ResourceTemplate] = {}
        self.global_template_handlers: dict[str, ResourceHandler] = {}

        self.client_resources: dict[
            str, dict[str, Resource]
        ] = {}  # client_id -> {uri: resource}
        self.client_handlers: dict[str, dict[str, ResourceHandler]] = {}

        self.client_templates: dict[str, dict[str, ResourceTemplate]] = {}
        self.client_template_handlers: dict[str, dict[str, ResourceHandler]] = {}

        self._client_subscriptions: dict[str, set[str]] = {}  # client_id -> {uri, ...}

        self.subscribe_handler: SubscriptionCallback | None = None
        self.unsubscribe_handler: SubscriptionCallback | None = None
        self.logger = logging.getLogger("conduit.server.protocol.resources")

    # ===============================
    # Global resource management
    # ===============================

    def add_resource(
        self,
        resource: Resource,
        handler: ResourceHandler,
    ) -> None:
        """Add a global resource with its handler function.

        Args:
            resource: Resource definition with URI and metadata.
            handler: Async function that processes read requests.
                Must take client_id and ReadResourceRequest as arguments and return a
                ReadResourceResult.
        """
        self.global_resources[resource.uri] = resource
        self.global_handlers[resource.uri] = handler

    def add_template(
        self,
        template: ResourceTemplate,
        handler: ResourceHandler,
    ) -> None:
        """Add a global resource template with its handler function.

        Args:
            template: ResourceTemplate definition with URI pattern and metadata.
            handler: Async function that processes read requests. Must take client_id
                and ReadResourceRequest as arguments and return a ReadResourceResult.
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
        handler: ResourceHandler,
    ) -> None:
        """Add a resource specific to a client.

        Overrides global resources with the same URI for this client.

        Args:
            client_id: ID of the client this resource is specific to.
            resource: Resource definition with URI and metadata.
            handler: Async function that processes read requests. Must take client_id
                and ReadResourceRequest as arguments and return a ReadResourceResult.
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
        handler: ResourceHandler,
    ) -> None:
        """Add a resource template specific to a client.

        Overrides global templates with the same URI pattern for this client.

        Args:
            client_id: ID of the client this template is specific to.
            template: ResourceTemplate definition with URI pattern and metadata.
            handler: Async function that processes read requests. Must take client_id
                and ReadResourceRequest as arguments and return a ReadResourceResult.
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
        resources = deepcopy(self.global_resources)

        if client_id in self.client_resources:
            for uri, resource in self.client_resources[client_id].items():
                if uri in resources:
                    self.logger.info(
                        f"Client {client_id} overriding global resource '{uri}'"
                    )
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
        templates = deepcopy(self.global_templates)

        if client_id in self.client_templates:
            for pattern, template in self.client_templates[client_id].items():
                if pattern in templates:
                    self.logger.info(
                        f"Client {client_id} overriding global template '{pattern}'"
                    )
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
        self, context: "RequestContext", request: ListResourcesRequest
    ) -> ListResourcesResult:
        """List all resources available to a specific client."""
        resources = self.get_client_resources(context.client_id)
        return ListResourcesResult(resources=list(resources.values()))

    async def handle_list_templates(
        self, context: "RequestContext", request: ListResourceTemplatesRequest
    ) -> ListResourceTemplatesResult:
        """List all resource templates available to a specific client."""
        templates = self.get_client_templates(context.client_id)
        return ListResourceTemplatesResult(resource_templates=list(templates.values()))

    async def handle_read(
        self, context: "RequestContext", request: ReadResourceRequest
    ) -> ReadResourceResult:
        """Read a resource by URI for a specific client.

        Args:
            context: Rich request context with client state and helpers
            request: Read resource request with URI

        Returns:
            ReadResourceResult: Resource content from the handler

        Raises:
            KeyError: If there is no matching resource or template.
            Exception: Any exception from the resource handler
        """
        uri = request.uri

        # Check client-specific handlers first
        if (
            context.client_id in self.client_handlers
            and uri in self.client_handlers[context.client_id]
        ):
            return await self.client_handlers[context.client_id][uri](context, request)
        elif uri in self.global_handlers:
            return await self.global_handlers[uri](context, request)

        # Check client-specific template handlers
        if context.client_id in self.client_template_handlers:
            for template_pattern, handler in self.client_template_handlers[
                context.client_id
            ].items():
                if self._matches_template(uri=uri, template=template_pattern):
                    return await handler(context, request)

        # Check global template handlers
        for template_pattern, handler in self.global_template_handlers.items():
            if self._matches_template(uri=uri, template=template_pattern):
                return await handler(context, request)

        raise KeyError(f"No resource or template handler found for URI: {uri}")

    async def handle_subscribe(
        self, context: "RequestContext", request: SubscribeRequest
    ) -> EmptyResult:
        """Subscribe a client to resource updates for the given URI.

        Args:
            context: Rich request context with client state and helpers
            request: Subscribe request with URI

        Returns:
            EmptyResult: Subscription confirmation

        Raises:
            ValueError: If URI is not valid or subscription fails
        """
        uri = request.uri
        client_id = context.client_id
        resource_exists = False

        client_resources = self.get_client_resources(client_id)
        if uri in client_resources:
            resource_exists = True
        else:
            client_templates = self.get_client_templates(client_id)
            for template_pattern in client_templates.keys():
                if self._matches_template(uri=uri, template=template_pattern):
                    resource_exists = True
                    break

        if not resource_exists:
            raise KeyError(f"Cannot subscribe to unknown resource: {uri}")

        client_subscriptions = self._client_subscriptions.setdefault(client_id, set())
        client_subscriptions.add(uri)

        if self.subscribe_handler:
            try:
                await self.subscribe_handler(client_id, uri)
            except Exception as e:
                self.logger.warning(
                    f"Error in subscribe handler for {client_id}: {uri}: {e}"
                )

        return EmptyResult()

    async def handle_unsubscribe(
        self, context: "RequestContext", request: UnsubscribeRequest
    ) -> EmptyResult:
        """Unsubscribe a client from resource updates for the given URI.

        Args:
            context: Rich request context with client state and helpers
            request: Unsubscribe request with URI

        Returns:
            EmptyResult: Unsubscription confirmation

        Raises:
            KeyError: If the client is not subscribed to the given URI
        """
        uri = request.uri
        client_id = context.client_id

        client_subscriptions = self._client_subscriptions.get(client_id, set())

        if uri not in client_subscriptions:
            raise KeyError(f"Client not subscribed to resource: {uri}")

        self._client_subscriptions[client_id].remove(uri)

        if self.unsubscribe_handler:
            try:
                await self.unsubscribe_handler(client_id, uri)
            except Exception as e:
                self.logger.warning(
                    f"Error in unsubscribe handler for {client_id}: {uri}: {e}"
                )

        return EmptyResult()

    def _matches_template(self, uri: str, template: str) -> bool:
        """Checks if a URI matches a URI template pattern."""
        pattern = re.escape(template)
        pattern = re.sub(r"\\{[^}]+\\}", r"([^/]+)", pattern)
        pattern = f"^{pattern}$"

        return bool(re.match(pattern, uri))

import asyncio
from dataclasses import dataclass, field

from conduit.protocol.base import INTERNAL_ERROR, Error, Request, Result
from conduit.protocol.initialization import Implementation, ServerCapabilities
from conduit.protocol.prompts import Prompt
from conduit.protocol.resources import Resource, ResourceTemplate
from conduit.protocol.tools import Tool

RequestID = str | int


@dataclass
class ServerContext:
    """Complete server state in one place."""

    # Protocol state
    capabilities: ServerCapabilities | None = None
    info: Implementation | None = None
    protocol_version: str | None = None
    instructions: str | None = None
    initialized: bool = False

    # Domain state
    tools: list[Tool] | None = None
    resources: list[Resource] | None = None
    resource_templates: list[ResourceTemplate] | None = None
    prompts: list[Prompt] | None = None

    # Request tracking
    requests_from_server: dict[RequestID, tuple[Request, asyncio.Task[None]]] = field(
        default_factory=dict
    )
    requests_to_server: dict[
        RequestID, tuple[Request, asyncio.Future[Result | Error]]
    ] = field(default_factory=dict)


class ServerManager:
    """Owns all server state and lifecycle."""

    def __init__(self):
        self._server_context = ServerContext()

    def get_server_context(self) -> ServerContext:
        """Get the server context."""
        return self._server_context

    def cleanup_requests(self) -> None:
        """Clean up all request tracking when stopping.

        Cancels work for requests the server is waiting on and resolves pending
        requests the server is fulfilling.
        """
        context = self._server_context

        for request, task in context.requests_from_server.values():
            task.cancel()
        context.requests_from_server.clear()

        for _, future in context.requests_to_server.values():
            if not future.done():
                error = Error(
                    code=INTERNAL_ERROR,
                    message="Request failed. Client coordinator stopped.",
                )
                future.set_result(error)
        context.requests_to_server.clear()

    def track_request_from_server(
        self,
        request_id: str | int,
        request: Request,
        task: asyncio.Task[None],
    ) -> None:
        """Track a request from the server.

        Args:
            request_id: Unique request identifier
            task: The task handling the request
        """
        context = self._server_context
        context.requests_from_server[request_id] = (request, task)

    def get_request_from_server(
        self, request_id: str | int
    ) -> tuple[Request, asyncio.Task[None]] | None:
        """Get a pending request from the server.

        Args:
            request_id: Request identifier to get

        Returns:
            Tuple of (request, task) if found, None otherwise
        """
        context = self._server_context
        return context.requests_from_server.get(request_id, None)

    def untrack_request_from_server(
        self, request_id: str | int
    ) -> tuple[Request, asyncio.Task[None]] | None:
        """Stop tracking a request from the server.

        Args:
            request_id: Request identifier to remove

        Returns:
            Tuple of (request, task) if found, None otherwise
        """
        context = self._server_context
        return context.requests_from_server.pop(request_id, None)

    def track_request_to_server(
        self,
        request_id: str,
        request: Request,
        future: asyncio.Future[Result | Error],
    ) -> None:
        """Track a pending request to the server.

        Args:
            request_id: Unique request identifier
            request: The original request object
            future: Future that will be resolved with the response
        """
        context = self._server_context
        context.requests_to_server[request_id] = (request, future)

    def untrack_request_to_server(
        self, request_id: str
    ) -> tuple[Request, asyncio.Future[Result | Error]] | None:
        """Stop tracking a request to the server.

        Args:
            request_id: Request identifier to remove

        Returns:
            Tuple of (request, future) if found, None otherwise
        """
        context = self._server_context
        return context.requests_to_server.pop(request_id, None)

    def get_request_to_server(
        self, request_id: str | int
    ) -> tuple[Request, asyncio.Future[Result | Error]] | None:
        """Get a pending request to the server.

        Args:
            request_id: Request identifier to get

        Returns:
            Tuple of (request, future) if found, None otherwise
        """
        context = self._server_context
        return context.requests_to_server.get(request_id, None)

    def resolve_request_to_server(
        self, request_id: str | int, result_or_error: Result | Error
    ) -> None:
        """Resolve a pending request to the server.

        Sets the future and clears the request from the server context.

        Args:
            request_id: Request identifier to resolve
            result_or_error: Result or error to resolve the request with
        """
        context = self._server_context
        request_future_tuple = context.requests_to_server.pop(request_id, None)
        if request_future_tuple:
            request, future = request_future_tuple
            future.set_result(result_or_error)

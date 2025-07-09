import asyncio
from dataclasses import dataclass, field

from conduit.protocol.base import INTERNAL_ERROR, Error, Request, Result
from conduit.protocol.initialization import ClientCapabilities, Implementation
from conduit.protocol.logging import LoggingLevel
from conduit.protocol.roots import Root


@dataclass
class ClientContext:
    """Complete client state in one place."""

    id: str

    # Protocol state
    capabilities: ClientCapabilities | None = None
    info: Implementation | None = None
    protocol_version: str | None = None
    initialized: bool = False

    # Domain state
    roots: list[Root] | None = None
    log_level: LoggingLevel | None = None
    subscriptions: set[str] = field(default_factory=set)

    # Request tracking
    requests_from_client: dict[str | int, asyncio.Task[None]] = field(
        default_factory=dict
    )
    requests_to_client: dict[
        str | int, tuple[Request, asyncio.Future[Result | Error]]
    ] = field(default_factory=dict)


class ClientManager:
    """Owns all client state and lifecycle."""

    def __init__(self):
        self._clients: dict[str, ClientContext] = {}

    def register_client(self, client_id: str) -> ClientContext:
        """Register new client connection."""
        context = ClientContext(id=client_id)
        self._clients[client_id] = context
        return context

    def get_client(self, client_id: str) -> ClientContext | None:
        """Get client context."""
        return self._clients.get(client_id)

    def is_client_initialized(self, client_id: str) -> bool:
        """Check if a specific client is initialized."""
        context = self.get_client(client_id)
        if context is None:
            return False

        return context.initialized

    def client_count(self) -> int:
        """Get number of active clients."""
        return len(self._clients)

    def disconnect_client(self, client_id: str) -> None:
        """Clean up all client state for a disconnected client.

        Cancels all in-flight requests from the client and resolves all pending
        requests to the client with an error.
        """
        context = self.get_client(client_id)
        if context is None:
            return

        for task in context.requests_from_client.values():
            task.cancel()
        context.requests_from_client.clear()

        for _, future in context.requests_to_client.values():
            if not future.done():
                error = Error(
                    code=INTERNAL_ERROR,
                    message="Request failed. Client disconnected.",
                )
                future.set_result(error)
        context.requests_to_client.clear()

        del self._clients[client_id]

    def cleanup_all_clients(self) -> None:
        """Clean up all client connections and state."""
        for client_id in list(self._clients.keys()):
            self.disconnect_client(client_id)

    def track_request_to_client(
        self,
        client_id: str,
        request_id: str,
        request: Request,
        future: asyncio.Future[Result | Error],
    ) -> None:
        """Track a pending request for a client.

        Args:
            client_id: ID of the client
            request_id: Unique request identifier
            request: The original request object
            future: Future that will be resolved with the response

        Raises:
            ValueError: If client doesn't exist
        """
        context = self.get_client(client_id)
        if context is None:
            raise ValueError(f"Client {client_id} not registered")

        context.requests_to_client[request_id] = (request, future)

    def remove_request_to_client(
        self, client_id: str, request_id: str
    ) -> tuple[Request, asyncio.Future[Result | Error]] | None:
        """Remove and return a pending request.

        Args:
            client_id: ID of the client
            request_id: Request identifier to remove

        Returns:
            Tuple of (request, future) if found, None otherwise
        """
        context = self.get_client(client_id)
        if context is None:
            return None

        return context.requests_to_client.pop(request_id, None)

    def get_request_to_client(
        self, client_id: str, request_id: str
    ) -> tuple[Request, asyncio.Future[Result | Error]] | None:
        """Get a pending request without removing it.

        Args:
            client_id: ID of the client
            request_id: Request identifier to look up

        Returns:
            Tuple of (request, future) if found, None otherwise
        """
        context = self.get_client(client_id)
        if context is None:
            return None

        return context.requests_to_client.get(request_id)

    def resolve_request_to_client(
        self, client_id: str, request_id: str, result_or_error: Result | Error
    ) -> bool:
        """Resolve a pending request with the parsed response.

        Args:
            client_id: ID of the client
            request_id: Request identifier to resolve
            result_or_error: Parsed response from the coordinator

        Returns:
            True if request was found and resolved, False otherwise
        """
        context = self.get_client(client_id)
        if context is None:
            return False

        request_future_tuple = context.requests_to_client.pop(request_id, None)
        if not request_future_tuple:
            return False

        original_request, future = request_future_tuple
        future.set_result(result_or_error)
        return True

    def track_request_from_client(
        self,
        client_id: str,
        request_id: str | int,
        task: asyncio.Task[None],
    ) -> None:
        """Track a request from a client.

        Args:
            client_id: ID of the client
            request_id: Unique request identifier
            task: The task handling the request

        Raises:
            ValueError: If client doesn't exist
        """
        context = self.get_client(client_id)
        if context is None:
            raise ValueError(f"Client {client_id} not registered")

        context.requests_from_client[request_id] = task

    def remove_request_from_client(
        self, client_id: str, request_id: str | int
    ) -> asyncio.Task[None] | None:
        """Remove and return a request from client.

        Args:
            client_id: ID of the client
            request_id: Request identifier to remove

        Returns:
            The task if found, None otherwise
        """
        context = self.get_client(client_id)
        if context is None:
            return None

        return context.requests_from_client.pop(request_id, None)

    def get_request_from_client(
        self, client_id: str, request_id: str | int
    ) -> asyncio.Task[None] | None:
        """Get a request from client without removing it.

        Args:
            client_id: ID of the client
            request_id: Request identifier to look up

        Returns:
            The task if found, None otherwise
        """
        context = self.get_client(client_id)
        if context is None:
            return None

        return context.requests_from_client.get(request_id)

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
    in_flight_requests: dict[str | int, asyncio.Task[None]] = field(
        default_factory=dict
    )
    pending_requests: dict[
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

    def disconnect_client(self, client_id: str) -> None:
        """Clean up all client state for a disconnected client."""
        context = self.get_client(client_id)
        if context is None:
            return

        # Cancel in-flight requests FROM this client
        for task in context.in_flight_requests.values():
            task.cancel()
        context.in_flight_requests.clear()

        # Resolve pending requests TO this client with errors
        for _, future in context.pending_requests.values():
            if not future.done():
                error = Error(
                    code=INTERNAL_ERROR,
                    message="Request failed. Client disconnected.",
                )
                future.set_result(error)
        context.pending_requests.clear()

        # Remove client entirely
        del self._clients[client_id]

    def cleanup_all_clients(self) -> None:
        """Clean up all client connections and state."""
        for client_id in list(self._clients.keys()):
            self.disconnect_client(client_id)

    def active_clients(self) -> set[str]:
        """Get IDs of all active clients."""
        return set(self._clients.keys())

    def client_count(self) -> int:
        """Get number of active clients."""
        return len(self._clients)

    def track_pending_request(
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

        context.pending_requests[request_id] = (request, future)

    def remove_pending_request(
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

        return context.pending_requests.pop(request_id, None)

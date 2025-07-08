import asyncio
from dataclasses import dataclass, field

from conduit.protocol.base import Error, Request, Result
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
        if client_id not in self._clients:
            return

        context = self._clients[client_id]

        # Cancel in-flight requests FROM this client
        for task in context.in_flight_requests.values():
            task.cancel()
        context.in_flight_requests.clear()

        # Cancel pending requests TO this client
        for _, future in context.pending_requests.values():
            future.cancel()
        context.pending_requests.clear()

        # Remove client entirely
        del self._clients[client_id]

    def cleanup_all_clients(self) -> None:
        """Clean up all client connections and state."""
        for client_id in list(self._clients.keys()):
            self.disconnect_client(client_id)

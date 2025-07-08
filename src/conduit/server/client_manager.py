import asyncio
from dataclasses import dataclass, field

from conduit.protocol.base import Error, Result
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
    in_flight_requests: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    pending_requests: dict[str, asyncio.Future[Result | Error]] = field(
        default_factory=dict
    )


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
        """Clean up all client state."""
        if client_id in self._clients:
            # Cancel all in-flight requests
            context = self._clients[client_id]
            for task in context.in_flight_requests.values():
                task.cancel()
            del self._clients[client_id]

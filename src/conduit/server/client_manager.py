import asyncio
from dataclasses import dataclass

from conduit.protocol.base import Error, Request, Result
from conduit.protocol.initialization import ClientCapabilities, Implementation
from conduit.protocol.roots import Root
from conduit.shared.request_tracker import RequestTracker


@dataclass
class ClientState:
    # Protocol state
    capabilities: ClientCapabilities | None = None
    info: Implementation | None = None
    protocol_version: str | None = None
    initialized: bool = False

    # Domain state
    roots: list[Root] | None = None


class ClientManager:
    """Owns all client state and manages request tracking."""

    def __init__(self):
        self._clients: dict[str, ClientState] = {}
        self.request_tracker = RequestTracker()

    # ================================
    # Registration
    # ================================

    def register_client(self, client_id: str) -> ClientState:
        """Register new client connection."""
        state = ClientState()
        self._clients[client_id] = state
        return state

    def get_client(self, client_id: str) -> ClientState | None:
        """Get client state."""
        return self._clients.get(client_id)

    def get_client_ids(self) -> list[str]:
        """Get all client IDs."""
        return list(self._clients.keys())

    def client_count(self) -> int:
        """Get number of active clients."""
        return len(self._clients)

    # ================================
    # Initialization
    # ================================

    def initialize_client(
        self,
        client_id: str,
        capabilities: ClientCapabilities,
        client_info: Implementation,
        protocol_version: str,
    ) -> None:
        """Register a client and store its initialization data."""
        state = self.get_client(client_id)
        if state is None:
            state = self.register_client(client_id)

        state.capabilities = capabilities
        state.info = client_info
        state.protocol_version = protocol_version

        state.initialized = True

    def is_protocol_initialized(self, client_id: str) -> bool:
        """Check if a specific client has completed MCP protocol initialization."""
        state = self.get_client(client_id)
        if state is None:
            return False

        return state.initialized

    # ================================
    # Outbound requests
    # ================================

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
        state = self.get_client(client_id)
        if state is None:
            raise ValueError(f"Client {client_id} not registered")

        self.request_tracker.track_outbound_request(
            client_id, request_id, request, future
        )

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
        return self.request_tracker.get_outbound_request(client_id, request_id)

    def resolve_request_to_client(
        self, client_id: str, request_id: str, result_or_error: Result | Error
    ) -> None:
        """Resolve a pending request with a result or error.

        Args:
            client_id: ID of the client
            request_id: Request identifier to resolve
            result_or_error: Result or error to resolve the request with
        """
        self.request_tracker.resolve_outbound_request(
            client_id, request_id, result_or_error
        )

    def remove_request_to_client(self, client_id: str, request_id: str) -> None:
        """Stop tracking a request to the client.

        Args:
            client_id: ID of the client
            request_id: Request identifier to remove
        """
        self.request_tracker.remove_outbound_request(client_id, request_id)

    # ================================
    # Inbound requests
    # ================================

    def track_request_from_client(
        self,
        client_id: str,
        request_id: str | int,
        request: Request,
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
        state = self.get_client(client_id)
        if state is None:
            raise ValueError(f"Client {client_id} not registered")

        self.request_tracker.track_inbound_request(client_id, request_id, request, task)

    def get_request_from_client(
        self, client_id: str, request_id: str | int
    ) -> tuple[Request, asyncio.Task[None]] | None:
        """Get a request from client without removing it.

        Args:
            client_id: ID of the client
            request_id: Request identifier to look up

        Returns:
            Tuple of (request, task) if found, None otherwise
        """
        return self.request_tracker.get_inbound_request(client_id, request_id)

    def cancel_request_from_client(self, client_id: str, request_id: str | int) -> None:
        """Cancel a request from the client.

        Args:
            client_id: ID of the client
            request_id: Request identifier to cancel
        """
        self.request_tracker.cancel_inbound_request(client_id, request_id)

    def remove_request_from_client(self, client_id: str, request_id: str | int) -> None:
        """Stop tracking a request from the client.

        Cancels the request as well.

        Args:
            client_id: ID of the client
            request_id: Request identifier to remove
        """
        self.request_tracker.remove_inbound_request(client_id, request_id)

    # ================================
    # Cleanup
    # ================================

    def cleanup_client(self, client_id: str) -> None:
        """Clean up all client state for a disconnected client.

        Cancels all in-flight requests from the client and resolves all pending
        requests to the client with an error.
        """
        self.request_tracker.cleanup_peer(client_id)
        self._clients.pop(client_id, None)

    def cleanup_all_clients(self) -> None:
        """Clean up all client connections and state."""
        for client_id in list(self._clients.keys()):
            self.cleanup_client(client_id)

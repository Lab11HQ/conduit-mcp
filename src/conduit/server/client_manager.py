import asyncio
from dataclasses import dataclass, field

from conduit.protocol.base import INTERNAL_ERROR, Error, Request, Result
from conduit.protocol.initialization import ClientCapabilities, Implementation
from conduit.protocol.logging import LoggingLevel
from conduit.protocol.roots import Root

RequestId = str | int


@dataclass
class ClientState:
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
    requests_from_client: dict[RequestId, tuple[Request, asyncio.Task[None]]] = field(
        default_factory=dict
    )
    requests_to_client: dict[
        RequestId, tuple[Request, asyncio.Future[Result | Error]]
    ] = field(default_factory=dict)


class ClientManager:
    """Owns all client state and lifecycle."""

    def __init__(self):
        self._clients: dict[str, ClientState] = {}

    def register_client(self, client_id: str) -> ClientState:
        """Register new client connection."""
        state = ClientState(id=client_id)
        self._clients[client_id] = state
        return state

    def get_client(self, client_id: str) -> ClientState | None:
        """Get client state."""
        return self._clients.get(client_id)

    def get_client_ids(self) -> list[str]:
        """Get all client IDs."""
        return list(self._clients.keys())

    def is_protocol_initialized(self, client_id: str) -> bool:
        """Check if a specific client has completed MCP protocol initialization."""
        state = self.get_client(client_id)
        if state is None:
            return False

        return state.initialized

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

    def client_count(self) -> int:
        """Get number of active clients."""
        return len(self._clients)

    def cleanup_client(self, client_id: str) -> None:
        """Clean up all client state for a disconnected client.

        Cancels all in-flight requests from the client and resolves all pending
        requests to the client with an error.
        """
        state = self.get_client(client_id)
        if state is None:
            return

        for request, task in state.requests_from_client.values():
            task.cancel()
        state.requests_from_client.clear()

        for _, future in state.requests_to_client.values():
            if not future.done():
                error = Error(
                    code=INTERNAL_ERROR,
                    message="Request failed. Client disconnected.",
                )
                future.set_result(error)
        state.requests_to_client.clear()

        del self._clients[client_id]

    def cleanup_all_clients(self) -> None:
        """Clean up all client connections and state."""
        for client_id in list(self._clients.keys()):
            self.cleanup_client(client_id)

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

        state.requests_to_client[request_id] = (request, future)

    def untrack_request_to_client(
        self, client_id: str, request_id: str
    ) -> tuple[Request, asyncio.Future[Result | Error]] | None:
        """Stop tracking a request to the client.

        Args:
            client_id: ID of the client
            request_id: Request identifier to remove

        Returns:
            Tuple of (request, future) if found, None otherwise
        """
        state = self.get_client(client_id)
        if state is None:
            raise ValueError(f"Client {client_id} not registered")

        return state.requests_to_client.pop(request_id, None)

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
        state = self.get_client(client_id)
        if state is None:
            return None

        return state.requests_to_client.get(request_id)

    def resolve_request_to_client(
        self, client_id: str, request_id: str, result_or_error: Result | Error
    ) -> None:
        """Resolve a pending request with a result or error.

        Args:
            client_id: ID of the client
            request_id: Request identifier to resolve
            result_or_error: Result or error to resolve the request with
        """
        client_state = self.get_client(client_id)
        if client_state is None:
            return

        request_future_tuple = client_state.requests_to_client.pop(request_id, None)
        if request_future_tuple:
            _, future = request_future_tuple
            future.set_result(result_or_error)

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

        state.requests_from_client[request_id] = (request, task)

    def untrack_request_from_client(
        self, client_id: str, request_id: str | int
    ) -> tuple[Request, asyncio.Task[None]] | None:
        """Stop tracking a request from the client.

        Args:
            client_id: ID of the client
            request_id: Request identifier to remove

        Returns:
            Tuple of (request, task) if found, None otherwise
        """
        state = self.get_client(client_id)
        if state is None:
            raise ValueError(f"Client {client_id} not registered")

        return state.requests_from_client.pop(request_id, None)

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
        state = self.get_client(client_id)
        if state is None:
            return None

        return state.requests_from_client.get(request_id)

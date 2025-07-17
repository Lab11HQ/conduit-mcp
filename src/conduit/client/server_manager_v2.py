import asyncio
from dataclasses import dataclass, field

from conduit.protocol.base import INTERNAL_ERROR, Error, Request, Result
from conduit.protocol.initialization import Implementation, ServerCapabilities
from conduit.protocol.prompts import Prompt
from conduit.protocol.resources import Resource, ResourceTemplate
from conduit.protocol.tools import Tool

RequestID = str | int


@dataclass
class ServerState:
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
        self._servers: dict[str, ServerState] = {}

    def register_server(self, server_id: str) -> ServerState:
        """Register a new server."""
        server_state = ServerState()
        self._servers[server_id] = server_state
        return server_state

    def get_server(self, server_id: str) -> ServerState | None:
        """Get a server state."""
        return self._servers.get(server_id)

    def get_all_server_ids(self) -> list[str]:
        """Get all server IDs."""
        return list(self._servers.keys())

    def is_protocol_initialized(self, server_id: str) -> bool:
        """Check if a specific server has completed MCP protocol initialization."""
        server_state = self.get_server(server_id)
        if server_state is None:
            return False

        return server_state.initialized

    def server_count(self) -> int:
        """Get number of active servers."""
        return len(self._servers)

    def initialize_server(
        self,
        server_id: str,
        capabilities: ServerCapabilities,
        info: Implementation,
        protocol_version: str,
        instructions: str | None = None,
    ) -> None:
        """Store the server's initialization data and mark it as initialized."""
        server_state = self.get_server(server_id)
        if server_state is None:
            server_state = self.register_server(server_id)

        server_state.capabilities = capabilities
        server_state.info = info
        server_state.protocol_version = protocol_version
        server_state.instructions = instructions
        server_state.initialized = True

    def cleanup_server(self, server_id: str) -> None:
        """Clean up all request tracking when stopping.

        Cancels work for requests the server is waiting on and resolves pending
        requests the server is fulfilling.
        """
        server_state = self.get_server(server_id)
        if server_state is None:
            return

        for request, task in server_state.requests_from_server.values():
            task.cancel()
        server_state.requests_from_server.clear()

        for _, future in server_state.requests_to_server.values():
            if not future.done():
                error = Error(
                    code=INTERNAL_ERROR,
                    message="Request failed. Client coordinator stopped.",
                )
                future.set_result(error)
        server_state.requests_to_server.clear()

    def cleanup_all_servers(self) -> None:
        """Clean up all server state."""
        for server_id in list(self._servers.keys()):
            self.cleanup_server(server_id)

    def track_request_to_server(
        self,
        server_id: str,
        request_id: str,
        request: Request,
        future: asyncio.Future[Result | Error],
    ) -> None:
        """Track a pending request to the server.

        Args:
            server_id: Server identifier
            request_id: Unique request identifier
            request: The original request object
            future: Future that will be resolved with the response

        Raises:
            ValueError: If server is not registered
        """
        server_state = self.get_server(server_id)
        if server_state is None:
            raise ValueError(f"Server {server_id} not registered")

        server_state.requests_to_server[request_id] = (request, future)

    def untrack_request_to_server(
        self, server_id: str, request_id: str
    ) -> tuple[Request, asyncio.Future[Result | Error]] | None:
        """Stop tracking a request to the server.

        Args:
            server_id: Server identifier
            request_id: Request identifier to remove

        Returns:
            Tuple of (request, future) if found, None otherwise

        Raises:
            ValueError: If server is not registered
        """
        server_state = self.get_server(server_id)
        if server_state is None:
            raise ValueError(f"Server {server_id} not registered")

        return server_state.requests_to_server.pop(request_id, None)

    def get_request_to_server(
        self, server_id: str, request_id: str
    ) -> tuple[Request, asyncio.Future[Result | Error]] | None:
        """Get a pending request to the server.

        Args:
            server_id: Server identifier
            request_id: Request identifier

        Returns:
            Tuple of (request, future) if found, None otherwise

        Raises:
            ValueError: If server is not registered
        """
        server_state = self.get_server(server_id)
        if server_state is None:
            raise ValueError(f"Server {server_id} not registered")

        return server_state.requests_to_server.get(request_id, None)

    def resolve_request_to_server(
        self, server_id: str, request_id: str, result_or_error: Result | Error
    ) -> None:
        """Resolve a pending request to the server.

        Sets the future and clears the request from the server context.

        Args:
            server_id: Server identifier
            request_id: Request identifier to resolve
            result_or_error: Result or error to resolve the request with

        Raises:
            ValueError: If server is not registered
        """
        server_state = self.get_server(server_id)
        if server_state is None:
            raise ValueError(f"Server {server_id} not registered")

        request_future_tuple = server_state.requests_to_server.pop(request_id, None)
        if request_future_tuple:
            request, future = request_future_tuple
            future.set_result(result_or_error)

    def track_request_from_server(
        self,
        server_id: str,
        request_id: str | int,
        request: Request,
        task: asyncio.Task[None],
    ) -> None:
        """Track a request from the server.

        Args:
            server_id: Server identifier
            request_id: Unique request identifier
            request: The original request object
            task: The task handling the request

        Raises:
            ValueError: If server is not registered
        """
        server_state = self.get_server(server_id)
        if server_state is None:
            raise ValueError(f"Server {server_id} not registered")

        server_state.requests_from_server[request_id] = (request, task)

    def untrack_request_from_server(
        self, server_id: str, request_id: str | int
    ) -> tuple[Request, asyncio.Task[None]] | None:
        """Stop tracking a request from the server.

        Args:
            server_id: Server identifier
            request_id: Request identifier to remove

        Returns:
            Tuple of (request, task) if found, None otherwise
        """
        server_state = self.get_server(server_id)
        if server_state is None:
            raise ValueError(f"Server {server_id} not registered")

        return server_state.requests_from_server.pop(request_id, None)

    def get_request_from_server(
        self, server_id: str, request_id: str | int
    ) -> tuple[Request, asyncio.Task[None]] | None:
        """Get a pending request from the server.

        Args:
            server_id: Server identifier
            request_id: Request identifier to get

        Returns:
            Tuple of (request, task) if found, None otherwise
        """
        server_state = self.get_server(server_id)
        if server_state is None:
            raise ValueError(f"Server {server_id} not registered")

        return server_state.requests_from_server.get(request_id, None)

import asyncio
from dataclasses import dataclass

from conduit.protocol.base import Error, Request, Result
from conduit.protocol.initialization import Implementation, ServerCapabilities
from conduit.protocol.prompts import Prompt
from conduit.protocol.resources import Resource, ResourceTemplate
from conduit.protocol.tools import Tool
from conduit.shared.request_tracker import RequestTracker


@dataclass
class ServerState:
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


class ServerManager:
    """Owns server state and manages request tracking."""

    def __init__(self):
        self._servers: dict[str, ServerState] = {}
        self.request_tracker = RequestTracker()

    # ================================
    # Registration
    # ================================

    def register_server(self, server_id: str) -> ServerState:
        """Register a new server.

        Args:
            server_id: Server identifier

        Returns:
            The ServerState object for the registered server.
        """
        server_state = ServerState()
        self._servers[server_id] = server_state
        return server_state

    def get_server(self, server_id: str) -> ServerState | None:
        """Get server state by ID.

        Args:
            server_id: Server identifier

        Returns:
            The server state or None if server is not registered.
        """
        return self._servers.get(server_id)

    def get_server_ids(self) -> list[str]:
        """Get IDs of all registered servers.

        Returns:
            List of server IDs.
        """
        return list(self._servers.keys())

    def server_count(self) -> int:
        """Get the number of registered servers."""
        return len(self._servers)

    # ================================
    # Initialization
    # ================================

    def initialize_server(
        self,
        server_id: str,
        capabilities: ServerCapabilities,
        info: Implementation,
        protocol_version: str,
        instructions: str | None = None,
    ) -> None:
        """Store the server's initialization data and mark it as initialized.

        Args:
            server_id: Server identifier
            capabilities: Server capabilities
            info: Server implementation info
            protocol_version: Protocol version
            instructions: Server instructions
        """
        server_state = self.get_server(server_id)
        if server_state is None:
            server_state = self.register_server(server_id)

        server_state.capabilities = capabilities
        server_state.info = info
        server_state.protocol_version = protocol_version
        server_state.instructions = instructions
        server_state.initialized = True

    def is_protocol_initialized(self, server_id: str) -> bool:
        """Check if a specific server has completed MCP initialization.

        Args:
            server_id: Server identifier

        Returns:
            True if server is initialized, False otherwise.
        """
        server_state = self.get_server(server_id)
        if server_state is None:
            return False

        return server_state.initialized

    # ================================
    # Outbound requests
    # ================================

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

        self.request_tracker.track_outbound_request(
            server_id, request_id, request, future
        )

    def get_request_to_server(
        self, server_id: str, request_id: str
    ) -> tuple[Request, asyncio.Future[Result | Error]] | None:
        """Get a pending request to the server.

        Args:
            server_id: Server identifier
            request_id: Request identifier

        Returns:
            Tuple of (request, future) if found, None otherwise
        """

        return self.request_tracker.get_outbound_request(server_id, request_id)

    def resolve_request_to_server(
        self, server_id: str, request_id: str, result_or_error: Result | Error
    ) -> None:
        """Resolve a pending request to the server.

        Sets the future and clears the request from the server context.

        Args:
            server_id: Server identifier
            request_id: Request identifier to resolve
            result_or_error: Result or error to resolve the request with
        """
        self.request_tracker.resolve_outbound_request(
            server_id, request_id, result_or_error
        )

    def remove_request_to_server(self, server_id: str, request_id: str) -> None:
        """Stop tracking a request to the server.

        Args:
            server_id: Server identifier
            request_id: Request identifier to remove
        """
        self.request_tracker.remove_outbound_request(server_id, request_id)

    # ================================
    # Inbound requests
    # ================================

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

        self.request_tracker.track_inbound_request(server_id, request_id, request, task)

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
        return self.request_tracker.get_inbound_request(server_id, request_id)

    def cancel_request_from_server(self, server_id: str, request_id: str | int) -> None:
        """Cancel a request from the server.

        Args:
            server_id: Server identifier
            request_id: Request identifier to cancel
        """
        self.request_tracker.cancel_inbound_request(server_id, request_id)

    def remove_request_from_server(self, server_id: str, request_id: str | int) -> None:
        """Stop tracking a request from the server.

        Args:
            server_id: Server identifier
            request_id: Request identifier to remove
        """
        self.request_tracker.remove_inbound_request(server_id, request_id)

    # ================================
    # Cleanup
    # ================================

    def cleanup_server(self, server_id: str) -> None:
        """Clean up all request tracking for a server.

        Cancels work for requests the server is waiting on and resolves pending
        requests the server is fulfilling.
        """
        self.request_tracker.cleanup_peer(server_id)
        self._servers.pop(server_id, None)

    def cleanup_all_servers(self) -> None:
        """Clean up all server state."""
        for server_id in list(self._servers.keys()):
            self.cleanup_server(server_id)

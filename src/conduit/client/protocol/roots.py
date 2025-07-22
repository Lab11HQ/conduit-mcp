import logging
from copy import deepcopy

from conduit.client.request_context import RequestContext
from conduit.protocol.roots import ListRootsRequest, ListRootsResult, Root


class RootsManager:
    def __init__(self):
        self._server_roots: dict[str, list[Root]] = {}
        self._global_roots: list[Root] = []
        self.logger = logging.getLogger("conduit.client.protocol.roots")

    # ================================
    # Global root management
    # ================================

    def add_root(self, root: Root) -> None:
        """Register a root that all servers can access."""
        self._global_roots.append(root)

    def get_roots(self) -> list[Root]:
        """Get all global roots."""
        return deepcopy(self._global_roots)

    def remove_root(self, uri: str) -> None:
        """Remove a global root by URI."""
        for i, root in enumerate(self._global_roots):
            if root.uri == uri:
                self._global_roots.pop(i)
                return
        return

    def clear_roots(self) -> None:
        """Remove all global roots."""
        self._global_roots.clear()

    # ================================
    # Server-specific root management
    # ================================

    def add_server_root(self, server_id: str, root: Root) -> None:
        """Register a root that only the specified server can access."""
        if server_id not in self._server_roots:
            self._server_roots[server_id] = []
        self._server_roots[server_id].append(root)

    def get_server_roots(self, server_id: str) -> list[Root]:
        """Get all roots available to a specific server."""
        roots_by_uri = {root.uri: root for root in self._global_roots}

        if server_id in self._server_roots:
            for root in self._server_roots[server_id]:
                if root.uri in roots_by_uri:
                    self.logger.debug(
                        f"Server {server_id} overriding global root '{root.uri}'"
                    )
                roots_by_uri[root.uri] = root

        return list(roots_by_uri.values())

    def remove_server_root(self, server_id: str, uri: str) -> None:
        """Remove a root by URI for a specific server."""
        if server_id not in self._server_roots:
            return

        for i, root in enumerate(self._server_roots[server_id]):
            if root.uri == uri:
                self._server_roots[server_id].pop(i)
                return

    def cleanup_server(self, server_id: str) -> None:
        """Clean up all state for a specific server."""
        self._server_roots.pop(server_id, None)

    # ================================
    # Protocol handlers
    # ================================

    async def handle_list_roots(
        self, context: RequestContext, request: ListRootsRequest
    ) -> ListRootsResult:
        """List the roots available to the server making the request."""
        roots = self.get_server_roots(context.server_id)
        return ListRootsResult(roots=roots)

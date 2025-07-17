from conduit.protocol.roots import ListRootsRequest, ListRootsResult, Root


class RootsManager:
    def __init__(self):
        # Server-specific roots (what each server knows about us)
        self._server_roots: dict[str, list[Root]] = {}
        # Global roots shared across all servers
        self._global_roots: list[Root] = []

    # ================================
    # Global root management (shared across all servers)
    # ================================

    def add_root(self, root: Root) -> None:
        """Register a root that all servers can access."""
        self._global_roots.append(root)

    def remove_root(self, uri: str) -> bool:
        """Remove a global root by URI. Returns True if found and removed."""
        for i, root in enumerate(self._global_roots):
            if root.uri == uri:
                self._global_roots.pop(i)
                return True
        return False

    def clear_roots(self) -> None:
        """Remove all global roots."""
        self._global_roots.clear()

    def get_global_roots(self) -> list[Root]:
        """Get all global roots."""
        return self._global_roots.copy()

    # ================================
    # Server-specific root management
    # ================================

    def add_root_to_server(self, server_id: str, root: Root) -> None:
        """Register a root that only the specified server can access."""
        if server_id not in self._server_roots:
            self._server_roots[server_id] = []
        self._server_roots[server_id].append(root)

    def remove_root_from_server(self, server_id: str, uri: str) -> bool:
        """Remove a root by URI for a specific server. Returns True if successful."""
        if server_id not in self._server_roots:
            return False

        for i, root in enumerate(self._server_roots[server_id]):
            if root.uri == uri:
                self._server_roots[server_id].pop(i)
                return True
        return False

    def clear_roots_for_server(self, server_id: str) -> None:
        """Remove all registered roots for a specific server."""
        self._server_roots.pop(server_id, None)

    def get_roots_for_server(self, server_id: str) -> list[Root]:
        """Get all roots available to a specific server (server-specific + global)."""
        server_specific = self._server_roots.get(server_id, [])
        return server_specific + self._global_roots

    def get_server_specific_roots(self, server_id: str) -> list[Root]:
        """Get only the server-specific roots for a server (excludes global)."""
        return self._server_roots.get(server_id, []).copy()

    # ================================
    # Server lifecycle
    # ================================

    def cleanup_server(self, server_id: str) -> None:
        """Clean up all state for a specific server."""
        self._server_roots.pop(server_id, None)

    # ================================
    # Protocol handler (server-aware)
    # ================================

    async def handle_list_roots(
        self, server_id: str, request: ListRootsRequest
    ) -> ListRootsResult:
        """Handle server request for filesystem roots."""
        roots = self.get_roots_for_server(server_id)
        return ListRootsResult(roots=roots)

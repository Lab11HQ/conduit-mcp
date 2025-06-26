from conduit.protocol.roots import ListRootsRequest, ListRootsResult, Root


class RootsManager:
    def __init__(self):
        self.roots: list[Root] = []

    def register_root(self, root: Root) -> None:
        """Register a root that the server can access."""
        self.roots.append(root)

    def unregister_root(self, uri: str) -> bool:
        """Remove a root by URI. Returns True if found and removed."""
        for i, root in enumerate(self.roots):
            if str(root.uri) == uri:
                self.roots.pop(i)
                return True
        return False

    def clear_roots(self) -> None:
        """Remove all registered roots."""
        self.roots.clear()

    async def handle_list_roots(self, request: ListRootsRequest) -> ListRootsResult:
        """Handle server request for filesystem roots."""
        return ListRootsResult(roots=self.roots)

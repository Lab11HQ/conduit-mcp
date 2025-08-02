from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from conduit.protocol.initialization import Implementation, ServerCapabilities

if TYPE_CHECKING:
    from conduit.client.server_manager import ServerManager, ServerState
    from conduit.transport.client import ClientTransport


@dataclass
class MessageContext:
    """Rich context for handling server -> client messages.

    Provides immediate access to server state, capabilities, and helper methods.
    """

    server_id: str
    server_state: ServerState
    server_manager: ServerManager
    transport: ClientTransport

    # ================================
    # Server Information
    # ================================

    @property
    def server_info(self) -> Implementation | None:
        """Get server implementation info (name, version)."""
        return self.server_state.info

    @property
    def server_capabilities(self) -> ServerCapabilities | None:
        """Get server capabilities."""
        return self.server_state.capabilities

    # ================================
    # Communication Helpers
    # ================================

    async def send_to_server(self, message: dict[str, Any]) -> None:
        """Send a message directly to this server."""
        await self.transport.send(self.server_id, message)

    # ================================
    # Context Helpers
    # ================================

    def get_server_display_name(self) -> str:
        """Get a human-readable name for this server."""
        if self.server_info and self.server_info.name:
            name = self.server_info.name
            if self.server_info.version:
                return f"{name} v{self.server_info.version}"
            return name
        return f"Server {self.server_id}"

    def __str__(self) -> str:
        """String representation for logging."""
        return (
            f"MessageContext(server={self.get_server_display_name()},"
            f"id={self.server_id})"
        )

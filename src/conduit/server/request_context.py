"""Rich request context for server request handlers.

Provides comprehensive client state and helper methods to request handlers,
replacing the bare client_id parameter with an empowering context object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from conduit.protocol.initialization import ClientCapabilities, Implementation
from conduit.protocol.roots import Root

if TYPE_CHECKING:
    from conduit.server.client_manager import ClientManager, ClientState
    from conduit.transport.server import ServerTransport


@dataclass
class RequestContext:
    """Rich context for handling client -> server requests.

    Provides immediate access to client state, capabilities, and helper methods
    instead of requiring handlers to work with bare client_id strings.

    This context is built once at the coordinator level and threaded through
    the request pipeline, giving handlers everything they need to make
    informed decisions about client capabilities and state.
    """

    client_id: str
    client_state: ClientState
    client_manager: ClientManager
    transport: ServerTransport

    # ================================
    # Client Information
    # ================================

    @property
    def client_info(self) -> Implementation | None:
        """Get client implementation info (name, version)."""
        return self.client_state.info

    @property
    def client_capabilities(self) -> ClientCapabilities | None:
        """Get client capabilities."""
        return self.client_state.capabilities

    @property
    def roots(self) -> list[Root] | None:
        """Get client's filesystem roots, if any."""
        return self.client_state.roots

    # ================================
    # Capability Checks
    # ================================

    def can_access_filesystem(self) -> bool:
        """True if client has provided filesystem roots."""
        return self.roots is not None and len(self.roots) > 0

    def supports_sampling(self) -> bool:
        """True if client supports sampling requests."""
        return (
            self.client_capabilities is not None and self.client_capabilities.sampling
        )

    # ================================
    # Communication Helpers
    # ================================

    async def send_to_client(self, message: dict[str, Any]) -> None:
        """Send a message directly to this client.

        Args:
            message: JSON-RPC message to send

        Raises:
            ConnectionError: If transport fails to send
        """
        await self.transport.send(self.client_id, message)

    # ================================
    # Context Helpers
    # ================================

    def get_client_display_name(self) -> str:
        """Get a human-readable name for this client."""
        if self.client_info and self.client_info.name:
            name = self.client_info.name
            if self.client_info.version:
                return f"{name} v{self.client_info.version}"
            return name
        return f"Client {self.client_id}"

    def __str__(self) -> str:
        """String representation for logging."""
        return (
            f"RequestContext(client={self.get_client_display_name()},"
            f"id={self.client_id})"
        )

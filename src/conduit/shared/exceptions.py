from typing import Any

from conduit.protocol.base import Error


class MCPError(Exception):
    """
    Exception type raised when an error arrives over an MCP connection.
    """

    def __init__(self, error: Error, transport_metadata: dict[str, Any] | None = None):
        """Initialize MCPError."""
        super().__init__(error.message)
        self.error = error
        self.transport_metadata = transport_metadata

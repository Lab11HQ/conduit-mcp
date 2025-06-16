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


class UnknownNotificationError(Exception):
    """Raised when receiving a notification with an unrecognized method."""

    def __init__(self, method: str):
        self.method = method
        super().__init__(f"Unknown notification method: {method}")


class UnknownRequestError(Exception):
    """Raised when receiving a request with an unrecognized method."""

    def __init__(self, method: str):
        self.method = method
        super().__init__(f"Unknown request method: {method}")

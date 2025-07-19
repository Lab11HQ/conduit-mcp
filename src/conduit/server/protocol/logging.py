from typing import Awaitable, Callable

from conduit.protocol.common import EmptyResult
from conduit.protocol.logging import LoggingLevel, SetLevelRequest


class LoggingManager:
    """Manages MCP protocol logging levels and notifications.

    Controls which log messages are sent to MCP clients via notifications.
    This is separate from your application's general logging configuration.
    """

    def __init__(self):
        # Client-specific log levels (what we manage FOR each client)
        self._client_log_levels: dict[str, LoggingLevel] = {}

        # Direct callback assignment
        self.level_change_handler: (
            Callable[[str, LoggingLevel], Awaitable[None]] | None
        ) = None

    def get_client_level(self, client_id: str) -> LoggingLevel | None:
        """Get the current logging level for a specific client."""
        return self._client_log_levels.get(client_id)

    def set_client_level(self, client_id: str, level: LoggingLevel) -> None:
        """Set logging level for a client (server-side management).

        Typically clients request their own levels via a SetLevelRequest, but
        servers may need to set defaults or administrative overrides.
        """
        self._client_log_levels[client_id] = level

    def cleanup_client(self, client_id: str) -> None:
        """Remove logging state for a disconnected client."""
        self._client_log_levels.pop(client_id, None)

    async def handle_set_level(
        self, client_id: str, request: SetLevelRequest
    ) -> EmptyResult:
        """Set the MCP protocol logging level for specific client."""
        # Store the level directly in our manager
        self._client_log_levels[client_id] = request.level

        # Notify via callback if configured
        if self.level_change_handler:
            try:
                await self.level_change_handler(client_id, request.level)
            except Exception as e:
                print(f"Error in level change handler for {client_id}: {e}")

        return EmptyResult()

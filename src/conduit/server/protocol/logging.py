import asyncio
from typing import Awaitable, Callable

from conduit.protocol.common import EmptyResult
from conduit.protocol.logging import LoggingLevel, SetLevelRequest
from conduit.server.client_manager import ClientManager


class LoggingManager:
    """Manages MCP protocol logging levels and notifications.

    Controls which log messages are sent to MCP clients via notifications.
    This is separate from your application's general logging configuration.
    """

    def __init__(self, client_manager: ClientManager):
        self.client_manager = client_manager
        self._on_level_change: Callable[[str, LoggingLevel], Awaitable[None]] | None = (
            None
        )

    def on_level_change(
        self, callback: Callable[[str, LoggingLevel], Awaitable[None]]
    ) -> None:
        """Set callback for log level changes with client context."""
        self._on_level_change = callback

    async def handle_set_level(
        self, client_id: str, request: SetLevelRequest
    ) -> EmptyResult:
        """Set the MCP protocol logging level for specific client."""
        context = self.client_manager.get_client(client_id)
        if context:
            context.log_level = request.level

        if self._on_level_change:
            try:
                asyncio.create_task(self._on_level_change(client_id, request.level))
            except Exception as e:
                print(f"Error in log level change callback for {client_id}: {e}")
        return EmptyResult()

    def get_client_level(self, client_id: str) -> LoggingLevel | None:
        """Get the current logging level for a specific client."""
        context = self.client_manager.get_client(client_id)
        return context.log_level if context else None

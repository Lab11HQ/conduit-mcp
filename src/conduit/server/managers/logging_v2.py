from typing import Awaitable, Callable

from conduit.protocol.common import EmptyResult
from conduit.protocol.logging import LoggingLevel, SetLevelRequest


class LoggingManager:
    """Manages MCP protocol logging levels and notifications.

    Controls which log messages are sent to MCP clients via notifications.
    This is separate from your application's general logging configuration.
    """

    def __init__(self):
        self.client_levels: dict[str, LoggingLevel] = {}
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
        self.client_levels[client_id] = request.level
        if self._on_level_change:
            try:
                await self._on_level_change(client_id, request.level)
            except Exception as e:
                print(f"Error in log level change callback for {client_id}: {e}")
        return EmptyResult()

    def get_client_level(self, client_id: str) -> LoggingLevel | None:
        """Get the current logging level for a specific client."""
        return self.client_levels.get(client_id)

    def should_send_log(self, level: LoggingLevel) -> bool:
        """Check if a log message should be sent based on current log level."""
        if self.current_level is None:
            return False

        priorities = {
            "debug": 0,
            "info": 1,
            "notice": 2,
            "warning": 3,
            "error": 4,
            "critical": 5,
            "alert": 6,
            "emergency": 7,
        }

        current_priority = priorities.get(self.current_level, 0)
        message_priority = priorities.get(level, 0)

        return message_priority >= current_priority

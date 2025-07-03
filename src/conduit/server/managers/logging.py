from typing import Awaitable, Callable

from conduit.protocol.common import EmptyResult
from conduit.protocol.logging import LoggingLevel, SetLevelRequest


class LoggingManager:
    """Manages MCP protocol logging levels and notifications.

    Controls which log messages are sent to MCP clients via notifications.
    This is separate from your application's general logging configuration.
    """

    def __init__(self):
        self.current_level: LoggingLevel | None = None
        self.on_level_change: Callable[[LoggingLevel], Awaitable[None]] | None = None

    def set_handler(self, handler: Callable[[LoggingLevel], Awaitable[None]]) -> None:
        """Set callback for log level changes."""
        self.on_level_change = handler

    async def handle_set_level(self, request: SetLevelRequest) -> EmptyResult:
        """Set the MCP protocol logging level.

        Updates the current logging level and calls the registered callback.
        Callback failures are logged but don't fail the operation since the
        level is successfully set and filtering will work correctly.

        Args:
            request: Set level request with the new logging level.

        Returns:
            EmptyResult: Level set successfully.
        """
        self.current_level = request.level
        if self.on_level_change:
            try:
                await self.on_level_change(request.level)
            except Exception as e:
                print(f"Error in log level change callback: {e}")
        return EmptyResult()

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

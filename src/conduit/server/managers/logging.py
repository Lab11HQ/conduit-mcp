from typing import Awaitable, Callable

from conduit.protocol.common import EmptyResult
from conduit.protocol.logging import LoggingLevel, SetLevelRequest


class LoggingManager:
    def __init__(self):
        self.current_level: LoggingLevel | None = None
        self.on_level_change: Callable[[LoggingLevel], Awaitable[None]] | None = None

    async def handle_set_level(self, request: SetLevelRequest) -> EmptyResult:
        """Handle log level change request."""
        self.current_level = request.level
        if self.on_level_change:
            await self.on_level_change(request.level)
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

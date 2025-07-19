"""
MCP Server Logging: Your window into what's happening behind the scenes.

Building an MCP application? Your server is doing important work—connecting to
databases, processing files, calling APIs—but when something goes wrong, you're flying
blind. That's where MCP's logging protocol comes in.

Think of it as a conversation between your client and server about visibility:

    Client: "I need to debug this. Show me what you're doing."
    Server: "How much detail do you want?"
    Client: "Start with errors, but I might need more if things get weird."
    Server: "Got it. Here's what's happening..."

The flow is simple:

1. **Request visibility**: Your client sends a `SetLevelRequest` to dial up the logging
2. **Stream insights**: The server responds with `LoggingMessageNotification`s as things
happen
3. **Adjust the firehose**: Client can change the level anytime to see more or less
detail

The logging levels follow syslog severity (RFC 5424), from `debug` (everything) to
`emergency` (the server is on fire). Choose your level based on what you're trying to
solve:

- `error` and above: "Something's broken, show me what"
- `info` and above: "I want to see the server's major decisions"
- `debug`: "I need to see everything"

Note: If you never send a `SetLevelRequest`, the server picks what to show you
automatically.
"""

from enum import Enum
from typing import Any, Literal

from pydantic import field_validator

from conduit.protocol.base import Notification, Request
from conduit.protocol.common import EmptyResult


class LoggingLevel(str, Enum):
    """
    Logging severity levels, following syslog standards (RFC 5424).

    When you set a level, you receive that level and all more severe levels.
    Common choices:
    - 'error': Only problems that need attention
    - 'info': Major server operations and errors
    - 'debug': Everything (verbose, use sparingly)
    """

    DEBUG = "debug"
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    ALERT = "alert"
    EMERGENCY = "emergency"


class SetLevelRequest(Request):
    """
    Tell the server what level of logging detail you want to receive.

    Send this to start receiving log notifications at your chosen severity level
    and above. You can send multiple requests to adjust the level dynamically
    as your debugging needs change.
    """

    method: Literal["logging/setLevel"] = "logging/setLevel"
    level: LoggingLevel
    """
    The minimum severity level for log messages you want to receive.
    """

    @classmethod
    def expected_result_type(cls) -> type[EmptyResult]:
        return EmptyResult

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, v: str) -> str:
        """Normalize logging level to lowercase to match MCP spec."""
        return v.lower()


class LoggingMessageNotification(Notification):
    """
    A log message sent from server to client.

    These notifications stream server activity in real-time. Each message
    includes severity level, log data, and an optional logger name. If no logging level
    was set, the server chooses what to send automatically.
    """

    method: Literal["notifications/message"] = "notifications/message"
    level: LoggingLevel
    """
    Severity level of this log message.
    """

    logger: str | None = None
    """
    Name of the logger that generated this message (optional).
    """

    data: Any
    """
    The log payload - typically a string message or structured data.
    
    Any JSON-serializable object is allowed.
    """

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, v: str) -> str:
        """Normalize logging level to lowercase to match MCP spec."""
        return v.lower()

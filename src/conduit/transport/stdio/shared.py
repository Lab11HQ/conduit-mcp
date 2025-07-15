import json
from typing import Any


def parse_json_message(line: str) -> dict[str, Any] | None:
    """Parse a line as JSON message.

    Args:
        line: Raw line from client stdin

    Returns:
        Parsed message dict, or None if invalid/should be ignored
    """
    line = line.strip()
    if not line:
        return None  # Ignore empty lines

    try:
        message = json.loads(line)
        if not isinstance(message, dict):
            return None
        return message
    except json.JSONDecodeError as e:
        return None


def serialize_message(message: dict[str, Any]) -> str:
    """Serialize message to JSON string with validation.

    Args:
        message: JSON-RPC message to serialize

    Returns:
        JSON string representation

    Raises:
        ValueError: If message contains embedded newlines
    """
    try:
        # Serialize to JSON with no extra whitespace
        json_str = json.dumps(message, separators=(",", ":"), ensure_ascii=False)

        # Validate no embedded newlines (spec requirement)
        if "\n" in json_str or "\r" in json_str:
            raise ValueError(
                "Message contains embedded newlines, which violates MCP spec"
            )

        return json_str

    except (TypeError, ValueError) as e:
        raise ValueError(f"Failed to serialize message to JSON: {e}") from e

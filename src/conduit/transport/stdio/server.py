import asyncio
import json
import sys
import time
from typing import Any, AsyncIterator

from conduit.transport.server import ClientMessage, ServerTransport


class StdioServerTransport(ServerTransport):
    """Stdio server transport for 1:1 client-server communication.

    Reads JSON-RPC messages from stdin and writes responses to stdout.
    The client manages our process lifecycle by launching us as a subprocess.
    """

    def __init__(self) -> None:
        """Initialize stdio server transport.

        No parameters needed - stdin/stdout are already connected to the client
        process that launched us as a subprocess.
        """
        self._client_id = "stdio-client"  # Dummy ID for 1:1 relationship
        self._is_open = True

    @property
    def is_open(self) -> bool:
        """True if server is open and accepting messages."""
        return self._is_open and not sys.stdin.closed and not sys.stdout.closed

    def _serialize_message(self, message: dict[str, Any]) -> str:
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

            # Validate no embedded newlines (MCP spec requirement)
            if "\n" in json_str or "\r" in json_str:
                raise ValueError(
                    "Message contains embedded newlines, which violates MCP spec"
                )

            return json_str

        except (TypeError, ValueError) as e:
            raise ValueError(f"Failed to serialize message to JSON: {e}") from e

    async def send(self, client_id: str, message: dict[str, Any]) -> None:
        """Send message to the client via stdout.

        Args:
            client_id: Ignored for stdio (always 1:1 relationship)
            message: JSON-RPC message to send

        Raises:
            ValueError: If message is invalid
            ConnectionError: If stdout is closed or write fails
        """
        if not self.is_open:
            raise ConnectionError("Transport is closed")

        try:
            # Serialize to JSON with no extra whitespace (match client format)
            json_str = self._serialize_message(message)

            # Write to stdout with newline delimiter
            print(json_str, file=sys.stdout, flush=True)

        except ValueError:
            raise
        except Exception as e:
            self._is_open = False
            raise ConnectionError(f"Failed to send message: {e}") from e

    def _parse_json_message(self, line: str) -> dict[str, Any] | None:
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
                # Log to stderr - client may capture this
                print(f"Warning: Message is not a JSON object: {line}", file=sys.stderr)
                return None
            return message
        except json.JSONDecodeError as e:
            # Log to stderr - client may capture this
            print(f"Warning: Invalid JSON received: {line} - {e}", file=sys.stderr)
            return None

    def client_messages(self) -> AsyncIterator[ClientMessage]:
        """Stream of messages from the client with explicit client context."""
        return self._client_message_iterator()

    async def _client_message_iterator(self) -> AsyncIterator[ClientMessage]:
        """Async iterator implementation for client messages."""
        stdin_reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(stdin_reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        try:
            while self.is_open:
                # Read one line from stdin
                line_bytes = await stdin_reader.readline()

                if not line_bytes:
                    # EOF - client closed stdin, exit gracefully
                    sys.exit(0)

                # Decode to string
                line = line_bytes.decode("utf-8")

                # Parse as JSON message
                message = self._parse_json_message(line)
                if message is not None:
                    # Wrap in ClientMessage with dummy client ID
                    client_message = ClientMessage(
                        client_id=self._client_id,
                        payload=message,
                        timestamp=time.time(),
                    )
                    yield client_message

        except Exception as e:
            self._is_open = False
            raise ConnectionError(f"Failed to read from stdin: {e}") from e
        finally:
            self._is_open = False

    async def close(self) -> None:
        """Close server transport and exit process.

        Closes stdout to signal the client that we're shutting down,
        then exits the process.
        """
        if not self._is_open:
            return

        self._is_open = False

        try:
            # Close stdout to signal client we're shutting down
            sys.stdout.close()
        except Exception:
            pass

        # Exit the process - client expects this
        sys.exit(0)

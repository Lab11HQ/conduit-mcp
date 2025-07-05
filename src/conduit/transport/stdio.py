import asyncio
import json
import sys
from collections.abc import AsyncIterator
from typing import Any

from conduit.transport.base import Transport, TransportMessage


class StdioTransport(Transport):
    """Stdio transport for MCP communication.

    Handles newline-delimited JSON over stdin/stdout.
    Works for both client and server sessions.
    """

    def __init__(self):
        self._is_open = True
        self._stdin_reader: asyncio.StreamReader | None = None
        self._stdout_writer: asyncio.StreamWriter | None = None

    @property
    def is_open(self) -> bool:
        """True if the transport is open and ready for message processing."""
        return self._is_open

    async def send(self, payload: dict[str, Any]) -> None:
        """Send a message via stdout.

        Args:
            payload: The MCP message to send

        Raises:
            ConnectionError: If transport is closed or stdout failed
        """
        if not self._is_open:
            raise ConnectionError("Transport is closed")

        try:
            # Serialize to JSON and add newline
            json_str = json.dumps(payload, separators=(",", ":"))
            message = json_str + "\n"

            # Write to stdout
            sys.stdout.write(message)
            sys.stdout.flush()

        except Exception as e:
            raise ConnectionError(f"Failed to send message: {e}") from e

    async def messages(self) -> AsyncIterator[TransportMessage]:
        """Stream of incoming messages from stdin.

        Yields messages as they arrive. Iterator ends when stdin closes.

        Yields:
            TransportMessage: Each incoming message with metadata

        Raises:
            ConnectionError: When stdin connection fails
            asyncio.CancelledError: When iteration is cancelled
        """
        if not self._is_open:
            return

        try:
            # Set up async stdin reader if not already done
            if self._stdin_reader is None:
                self._stdin_reader = asyncio.StreamReader()
                protocol = asyncio.StreamReaderProtocol(self._stdin_reader)
                loop = asyncio.get_event_loop()
                await loop.connect_read_pipe(lambda: protocol, sys.stdin)

            # Read messages line by line
            while self._is_open:
                try:
                    line = await self._stdin_reader.readline()

                    # EOF reached
                    if not line:
                        break

                    # Decode and parse JSON
                    line_str = line.decode("utf-8").strip()
                    if not line_str:  # Skip empty lines
                        continue

                    try:
                        payload = json.loads(line_str)
                    except json.JSONDecodeError as e:
                        # Log error but continue processing
                        print(f"Invalid JSON received: {e}", file=sys.stderr)
                        continue

                    # Yield the message
                    yield TransportMessage(
                        payload=payload, metadata={"source": "stdin"}
                    )

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    raise ConnectionError(f"Error reading from stdin: {e}") from e

        except Exception as e:
            raise ConnectionError(f"Failed to set up stdin reader: {e}") from e
        finally:
            await self.close()

    async def close(self) -> None:
        """Stop transport operations."""
        self._is_open = False
        self._stdin_reader = None

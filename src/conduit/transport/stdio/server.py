import asyncio
import sys
import time
from typing import Any, AsyncIterator

from conduit.transport.server import ClientMessage, ServerTransport
from conduit.transport.stdio.shared import parse_json_message, serialize_message


class StdioServerTransport(ServerTransport):
    """Stdio server transport for 1:1 client-server communication.

    Reads JSON-RPC messages from stdin and writes responses to stdout.
    The client manages our process lifecycle by launching us as a subprocess.
    """

    def __init__(self) -> None:
        """Initialize stdio server transport.

        Sets up async stdin reader for the single client connection.
        """
        self._client_id = "stdio-client"
        self._stdin_reader: asyncio.StreamReader | None = None

    async def _setup_stdin_reader(self) -> None:
        """Set up async stdin reader using protocol."""
        if self._stdin_reader is not None:
            return  # Already set up

        self._stdin_reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._stdin_reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    async def send(self, client_id: str, message: dict[str, Any]) -> None:
        """Send message to the client via stdout.

        Args:
            client_id: Ignored for stdio (always 1:1 relationship)
            message: JSON-RPC message to send

        Raises:
            ValueError: If message is invalid
            ConnectionError: If stdout is closed or write fails
        """
        try:
            json_str = serialize_message(message)
            print(json_str, file=sys.stdout, flush=True)
        except ValueError:
            raise
        except Exception as e:
            raise ConnectionError(f"Failed to send message: {e}") from e

    def client_messages(self) -> AsyncIterator[ClientMessage]:
        """Stream of messages from the client with explicit client context.

        Yields:
            ClientMessage: Message with client ID and metadata
        """
        return self._client_message_iterator()

    async def _client_message_iterator(self) -> AsyncIterator[ClientMessage]:
        """Async iterator implementation for client messages."""
        await self._setup_stdin_reader()

        try:
            while True:
                line_bytes = await self._stdin_reader.readline()

                if not line_bytes:
                    sys.exit(0)

                line = line_bytes.decode("utf-8")

                message = parse_json_message(line)
                if message is None:
                    print(
                        f"Warning: Invalid JSON received: {line.strip()}",
                        file=sys.stderr,
                    )
                    continue

                client_message = ClientMessage(
                    client_id=self._client_id,
                    payload=message,
                    timestamp=time.time(),
                )
                yield client_message

        except Exception as e:
            raise ConnectionError(f"Failed to read from stdin: {e}") from e

    async def disconnect_client(self, client_id: str) -> None:
        """Disconnect the client by closing stdout and exiting.

        Args:
            client_id: Ignored for stdio (always 1:1 relationship)
        """
        try:
            sys.stdout.close()
        except Exception:
            pass

        sys.exit(0)

    async def close(self) -> None:
        """Close the transport and clean up all resources."""
        try:
            sys.stdout.close()
        except Exception:
            pass

        sys.exit(0)

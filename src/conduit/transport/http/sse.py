import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

from httpx_sse import ServerSentEvent

from conduit.transport.base import TransportMessage


@dataclass
class SSEStreamConfig:
    """Configuration for SSE stream parsing."""

    stream_id: str
    stream_type: str  # "request", "listening", etc.
    source_url: str | None = None


class SSEStream:
    """Parses a single SSE stream into JSON-RPC messages.

    Takes an SSE event stream from httpx-sse and converts events to
    TransportMessage objects. Handles JSON parsing, error recovery,
    and stream lifecycle management.
    """

    def __init__(
        self, sse_events: AsyncIterator[ServerSentEvent], config: SSEStreamConfig
    ):
        self._sse_events = sse_events
        self._config = config
        self._closed = False

    @property
    def is_open(self) -> bool:
        """True if the stream is open and processing events."""
        return not self._closed

    @property
    def stream_id(self) -> str:
        """Unique identifier for this stream."""
        return self._config.stream_id

    async def messages(self) -> AsyncIterator[TransportMessage]:
        """Parse SSE events into JSON-RPC messages.

        Yields:
            TransportMessage: Each valid JSON-RPC message from the stream

        Raises:
            ConnectionError: When stream connection fails
            asyncio.CancelledError: When stream is cancelled
        """
        try:
            async for event in self._sse_events:
                if self._closed:
                    break

                # Handle different SSE event types
                if event.event == "close":
                    break

                # Parse JSON-RPC from event data
                message = self._parse_event(event)
                if message:
                    yield message

        except Exception as e:
            # Convert any parsing errors to connection errors
            raise ConnectionError(f"SSE stream {self.stream_id} failed: {e}") from e
        finally:
            self._closed = True

    def _parse_event(self, event: ServerSentEvent) -> TransportMessage | None:
        """Parse a single SSE event into a TransportMessage.

        Args:
            event: SSE event from httpx-sse

        Returns:
            TransportMessage if event contains valid JSON-RPC, None otherwise
        """
        if not event.data:
            return None

        try:
            # Parse JSON-RPC payload
            payload = json.loads(event.data)

            # Create transport metadata
            metadata = {
                "stream_id": self.stream_id,
                "stream_type": self._config.stream_type,
                "sse_event_type": event.event,
                "sse_event_id": event.id,
                "source_url": self._config.source_url,
            }

            return TransportMessage(payload=payload, metadata=metadata)

        except json.JSONDecodeError:
            # Log malformed JSON but don't crash the stream
            print(f"Malformed JSON in SSE stream {self.stream_id}: {event.data}")
            return None

    async def close(self) -> None:
        """Close the SSE stream and stop message processing."""
        self._closed = True

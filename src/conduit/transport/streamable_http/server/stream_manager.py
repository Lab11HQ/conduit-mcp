import logging
import uuid
from typing import Any

from conduit.transport.streamable_http.server.sse_stream import SSEStream

logger = logging.getLogger(__name__)


class StreamManager:
    """Manages multiple SSE streams with routing and cleanup."""

    def __init__(self):
        self._client_streams: dict[
            str, set[SSEStream]
        ] = {}  # client_id -> set of streams

    async def create_stream(
        self, client_id: str, request_id: str | None = None
    ) -> SSEStream:
        """Create and register a new stream."""
        stream_id = str(uuid.uuid4())
        stream = SSEStream(stream_id, client_id, request_id or "GET")

        # Track by client
        self._client_streams.setdefault(client_id, set()).add(stream)

        logger.debug(f"Created stream {stream_id} for client {client_id}")
        return stream

    async def send_to_existing_stream(
        self,
        client_id: str,
        message: dict[str, Any],
        originating_request_id: str | int | None = None,
    ) -> bool:
        """Send message to existing stream if available.

        Args:
            client_id: The client ID
            message: The message to send
            originating_request_id: The ID of the originating request. If provided,
                the message will be sent to the stream with the matching request ID.
                If not provided, the message will be sent to the first available
                stream (e.g. a stream created by a GET request).

        Returns:
            True if message was sent, False otherwise
        """
        streams = self._client_streams.get(client_id, set())

        if originating_request_id:
            for stream in streams:
                if stream.request_id == originating_request_id:
                    return await self._send_to_stream(
                        stream, message, auto_cleanup=True
                    )
        else:
            # Use any available stream (first one)
            if streams:
                stream = next(iter(streams))
                return await self._send_to_stream(stream, message, auto_cleanup=False)

        return False

    async def _send_to_stream(
        self, stream: SSEStream, message: dict[str, Any], auto_cleanup: bool
    ) -> bool:
        """Send message to a specific stream."""
        await stream.send_message(message)

        if auto_cleanup and stream.is_response(message):
            await self._cleanup_stream(stream)

        return True

    async def cleanup_client_streams(self, client_id: str) -> None:
        """Clean up all streams for a client."""
        streams = self._client_streams.get(client_id, set()).copy()
        for stream in streams:
            await self._cleanup_stream(stream)

        logger.debug(f"Cleaned up {len(streams)} streams for client {client_id}")

    def get_stream_by_id(self, stream_id: str) -> SSEStream | None:
        """Get stream by exact stream ID."""
        for streams in self._client_streams.values():
            for stream in streams:
                if stream.stream_id == stream_id:
                    return stream
        return None

    async def _cleanup_stream(self, stream: SSEStream) -> None:
        """Clean up a single stream."""
        # Close the stream (sends sentinel)
        await stream.close()

        # Remove from client tracking
        if stream.client_id in self._client_streams:
            self._client_streams[stream.client_id].discard(stream)
            if not self._client_streams[stream.client_id]:
                del self._client_streams[stream.client_id]

        logger.debug(f"Cleaned up stream {stream.stream_id}")

    async def close_all_streams(self) -> None:
        """Close all streams."""
        for streams in list(self._client_streams.values()):
            for stream in streams.copy():
                await self._cleanup_stream(stream)

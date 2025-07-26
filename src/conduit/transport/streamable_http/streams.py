import asyncio
import json
import logging
import uuid
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class SSEStream:
    """Manages a single SSE stream with proper lifecycle."""

    def __init__(self, stream_id: str, client_id: str, request_id: str | int):
        self.stream_id = stream_id
        self.client_id = client_id
        self.request_id = request_id
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def send_message(self, message: dict[str, Any]) -> None:
        """Send message on this stream."""
        await self._message_queue.put(message)

    async def send_response(self, response: dict[str, Any]) -> None:
        """Send final response and mark for auto-close."""
        await self.send_message(response)

    async def close(self) -> None:
        """Explicitly close the stream."""
        # Send sentinel to stop the generator
        await self._message_queue.put({"__close__": True})
        logger.debug(f"Manually closed stream {self.stream_id}")

    def is_response(self, message: dict[str, Any]) -> bool:
        """Check if message is the final response."""
        return "result" in message or "error" in message

    async def event_generator(self) -> AsyncIterator[str]:
        """Generate SSE events for this stream."""
        try:
            while True:
                message = await self._message_queue.get()

                # Check for explicit close sentinel
                if message.get("__close__"):
                    logger.debug(f"Stream {self.stream_id} closed via sentinel")
                    break

                # Format as SSE event
                event_data = json.dumps(message, separators=(",", ":"))
                yield f"data: {event_data}\n\n"

                # Auto-close after sending response
                if self.is_response(message):
                    logger.debug(
                        f"Response sent on stream {self.stream_id}, auto-closing"
                    )
                    break

        except Exception as e:
            logger.error(f"Error in stream {self.stream_id}: {e}")
        finally:
            logger.debug(f"Stream {self.stream_id} generator finished")


class StreamManager:
    """Manages multiple SSE streams with routing and cleanup."""

    def __init__(self):
        self._streams: dict[str, SSEStream] = {}  # stream_id -> stream
        self._client_streams: dict[str, set[str]] = {}  # client_id -> set of stream_ids

    async def create_request_stream(self, client_id: str, request_id: str) -> SSEStream:
        """Create and register a new stream for a specific request."""
        stream_id = f"{client_id}:request:{request_id}"
        return await self._create_and_register_stream(
            stream_id, client_id, str(request_id)
        )

    async def create_server_stream(self, client_id: str) -> SSEStream:
        """Create and register a new stream for server-initiated messages."""
        # Generate unique ID for this server stream

        stream_uuid = str(uuid.uuid4())[:8]  # Short UUID for readability
        stream_id = f"{client_id}:server:{stream_uuid}"

        return await self._create_and_register_stream(stream_id, client_id, None)

    async def send_to_existing_stream(
        self,
        client_id: str,
        message: dict[str, Any],
        originating_request_id: str | None = None,
    ) -> bool:
        """Send message to existing stream if available. Returns True if sent."""
        if originating_request_id:
            # Send to request-specific stream
            stream_id = f"{client_id}:request:{originating_request_id}"
            return await self._send_to_stream(stream_id, message, auto_cleanup=True)
        else:
            # Send to any available server stream (pick first one)
            server_streams = [
                sid
                for sid in self._client_streams.get(client_id, set())
                if sid.startswith(f"{client_id}:server:")
            ]

            if server_streams:
                # For now, just use the first available server stream
                # Could add more sophisticated routing later
                return await self._send_to_stream(
                    server_streams[0], message, auto_cleanup=False
                )

            return False

    async def _create_and_register_stream(
        self, stream_id: str, client_id: str, request_id: str | int | None
    ) -> SSEStream:
        """Create and register a stream."""
        stream = SSEStream(stream_id, client_id, request_id or "server")

        # Register it
        self._streams[stream_id] = stream

        # Track by client
        self._client_streams.setdefault(client_id, set()).add(stream_id)

        logger.debug(f"Created stream {stream_id} for client {client_id}")
        return stream

    async def _send_to_stream(
        self, stream_id: str, message: dict[str, Any], auto_cleanup: bool
    ) -> bool:
        """Send message to a specific stream."""
        stream = self._streams.get(stream_id)
        if not stream:
            logger.warning(f"No stream found for {stream_id}")
            return False

        await stream.send_message(message)

        # Clean up stream if this was a response and auto_cleanup is enabled
        if auto_cleanup and stream.is_response(message):
            await self._cleanup_stream(stream_id)

        return True

    async def cleanup_client_streams(self, client_id: str) -> None:
        """Clean up all streams for a client."""
        if client_id not in self._client_streams:
            return

        stream_ids = self._client_streams[client_id].copy()
        for stream_id in stream_ids:
            await self._cleanup_stream(stream_id)

        logger.debug(f"Cleaned up {len(stream_ids)} streams for client {client_id}")

    def get_stream_by_id(self, stream_id: str) -> SSEStream | None:
        """Get stream by exact stream ID."""
        return self._streams.get(stream_id)

    def get_request_stream(self, client_id: str, request_id: str) -> SSEStream | None:
        """Get specific request stream."""
        stream_id = f"{client_id}:request:{request_id}"
        return self._streams.get(stream_id)

    def get_server_streams(self, client_id: str) -> list[SSEStream]:
        """Get all server streams for a client."""
        server_streams = []
        for stream_id in self._client_streams.get(client_id, set()):
            if stream_id.startswith(f"{client_id}:server:"):
                stream = self._streams.get(stream_id)
                if stream:
                    server_streams.append(stream)
        return server_streams

    async def _cleanup_stream(self, stream_id: str) -> None:
        """Clean up a single stream."""
        if stream_id not in self._streams:
            return

        stream = self._streams[stream_id]

        # Close the stream (sends sentinel)
        await stream.close()

        # Remove from tracking
        del self._streams[stream_id]

        # Remove from client tracking
        if stream.client_id in self._client_streams:
            self._client_streams[stream.client_id].discard(stream_id)
            if not self._client_streams[stream.client_id]:
                del self._client_streams[stream.client_id]

        logger.debug(f"Cleaned up stream {stream_id}")

    def get_active_stream_count(self) -> int:
        """Get number of active streams (for debugging/metrics)."""
        return len(self._streams)

    def get_client_stream_count(self, client_id: str) -> int:
        """Get number of active streams for a client."""
        return len(self._client_streams.get(client_id, set()))

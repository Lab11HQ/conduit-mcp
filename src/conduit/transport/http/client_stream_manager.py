import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
from httpx_sse import aconnect_sse

from conduit.transport.base import TransportMessage
from conduit.transport.http.sse import SSEStream, SSEStreamConfig


class ClientStreamManager:
    """Manages multiple SSE streams FROM the server.

    Handles two types of streams:
    1. Listening stream (GET → SSE) for server-initiated messages
    2. Request streams (POST → SSE) for request responses

    Aggregates all streams into a unified message queue for the transport.
    """

    def __init__(self, endpoint_url: str, http_client: httpx.AsyncClient):
        self._endpoint_url = endpoint_url
        self._http_client = http_client

        # Stream management
        self._listening_streams: dict[str, SSEStream] = {}
        self._request_streams: dict[str, SSEStream] = {}

        # Unified message queue
        self._message_queue: asyncio.Queue[TransportMessage] = asyncio.Queue()
        self._stream_tasks: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    async def start_listening_stream(self) -> str | None:
        """Start the listening stream for server-initiated messages.

        Opens GET → SSE connection to receive notifications and requests
        that aren't related to client requests.
        """
        if self._closed:
            return
        stream_id = f"listening-{uuid.uuid4()}"

        try:
            # GET request with SSE headers
            sse_response = await aconnect_sse(
                self._http_client,
                "GET",
                self._endpoint_url,
                headers={"Accept": "text/event-stream"},
            )

            # Create SSE stream
            config = SSEStreamConfig(
                stream_id=stream_id,
                stream_type="listening",
                source_url=self._endpoint_url,
            )

            self._listening_streams[stream_id] = SSEStream(sse_response, config)

            # Start background task to process this stream
            task = asyncio.create_task(
                self._process_stream(self._listening_streams[stream_id])
            )

            self._stream_tasks[stream_id] = task

        except Exception as e:
            raise ConnectionError(f"Failed to start listening stream: {e}") from e

        return stream_id

    async def create_request_stream(self, request_id: str, sse_response) -> None:
        """Create a new request stream from a POST → SSE response.

        Args:
            request_id: ID of the request that triggered this stream
            sse_response: SSE response from httpx-sse
        """
        if self._closed:
            return

        config = SSEStreamConfig(
            stream_id=request_id, stream_type="request", source_url=self._endpoint_url
        )

        stream = SSEStream(sse_response, config)
        self._request_streams[request_id] = stream

        # Start background task to process this stream
        task = asyncio.create_task(self._process_stream(stream))
        self._stream_tasks[request_id] = task

    async def _process_stream(self, stream: SSEStream) -> None:
        """Process messages from a single SSE stream.

        Runs in background task, feeding messages into the unified queue.
        """
        try:
            async for message in stream.messages():
                if self._closed:
                    break
                await self._message_queue.put(message)
        except Exception as e:
            # Log stream error but don't crash the manager
            print(f"Stream {stream.stream_id} failed: {e}")
        finally:
            # Clean up completed stream
            await self._cleanup_stream(stream.stream_id)

    async def _cleanup_stream(self, stream_id: str) -> None:
        """Clean up a completed or failed stream."""
        # Remove from tracking
        self._request_streams.pop(stream_id, None)
        self._listening_streams.pop(stream_id, None)

        # Cancel task if still running
        task = self._stream_tasks.pop(stream_id, None)
        if task and not task.done():
            task.cancel()

    def messages(self) -> AsyncIterator[TransportMessage]:
        """Unified stream of messages from all SSE streams.

        Yields messages as they arrive from any active stream.
        """
        return self._message_queue_iterator()

    async def _message_queue_iterator(self) -> AsyncIterator[TransportMessage]:
        """Async iterator over the unified message queue."""
        while not self._closed:
            try:
                # Wait for next message with timeout to check closed status
                message = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield message
            except asyncio.TimeoutError:
                # Check if we should continue waiting
                continue

    async def close(self) -> None:
        """Close all streams and stop message processing."""
        self._closed = True

        # Cancel all stream tasks
        for task in self._stream_tasks.values():
            if not task.done():
                task.cancel()

        # Close all streams
        for stream in self._listening_streams.values():
            await stream.close()

        for stream in self._request_streams.values():
            await stream.close()

        # Clear tracking
        self._stream_tasks.clear()
        self._request_streams.clear()
        self._listening_streams.clear()

    # TODO: IS THIS RIGHT?
    def _inject_immediate_response(self, message: TransportMessage) -> None:
        """Inject an immediate response into the message queue."""
        self._message_queue.put_nowait(message)

    @property
    def is_open(self) -> bool:
        """True if the stream manager is open and processing messages."""
        return not self._closed

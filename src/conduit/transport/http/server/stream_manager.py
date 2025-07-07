import uuid
from collections.abc import AsyncIterator
from typing import Any

from conduit.transport.http.server.connection_manager import ConnectionManager


class StreamManager:
    """Manages outbound SSE streams TO multiple clients.

    Handles server → client message delivery via SSE streams:
    - Creates streams when server needs to send ongoing responses
    - Manages per-client stream tracking and cleanup
    - Handles per-stream resumability with event IDs
    - Supports both listening streams and request-response streams
    """

    def __init__(self, connection_manager: ConnectionManager):
        self._connection_manager = connection_manager

        # Per-client outbound streams
        self._client_streams: dict[str, dict[str, AsyncIterator[str]]] = {}
        # client_id -> {stream_id -> SSE_iterator}

        # Event ID tracking for resumability
        # Per-stream event counters
        self._stream_event_counters: dict[str, int] = {}
        # stream_id -> next_event_id

        # Per-stream event history for resumability
        self._stream_event_history: dict[str, list[tuple[int, str]]] = {}
        # stream_id -> [(event_id, sse_event_data), ...]

        self._closed = False

    async def create_listening_stream(
        self, client_id: str, last_event_id: str | None = None
    ) -> AsyncIterator[str]:
        """Create a listening stream for a client (handles GET requests).

        Args:
            client_id: Session ID of the client
            last_event_id: For resumability - replay from this event ID

        Yields:
            str: SSE-formatted events for the client

        Raises:
            ValueError: If client_id is not an active session
        """
        if not self._connection_manager.validate_session(client_id):
            raise ValueError(f"Invalid client session: {client_id}")

        stream_id = f"listening-{client_id}-{uuid.uuid4()}"

        # TODO: Implement listening stream
        # - Handle resumability with last_event_id
        # - Create message queue for this client
        # - Format messages as SSE events with event IDs
        # - Yield SSE strings

        # Track the stream
        if client_id not in self._client_streams:
            self._client_streams[client_id] = {}
        # self._client_streams[client_id][stream_id] = stream_iterator

        if last_event_id and stream_id in self._stream_event_history:
            await self._replay_stream_events(stream_id, int(last_event_id))

        # Placeholder
        yield f"data: {{'type': 'connected', 'client_id': '{client_id}'}}\n\n"

    async def create_request_stream(
        self, client_id: str, request_id: str
    ) -> AsyncIterator[str]:
        """Create a response stream for a specific client request.

        Args:
            client_id: Session ID of the client
            request_id: ID of the request that needs a streamed response

        Yields:
            str: SSE-formatted response events

        Raises:
            ValueError: If client_id is not an active session
        """
        if not self._connection_manager.validate_session(client_id):
            raise ValueError(f"Invalid client session: {client_id}")

        stream_id = f"request-{request_id}"

        # TODO: Implement request response stream
        # - Create dedicated queue for this request's responses
        # - Format responses as SSE events
        # - Handle stream completion

        # Track the stream
        if client_id not in self._client_streams:
            self._client_streams[client_id] = {}
        # self._client_streams[client_id][stream_id] = stream_iterator

        # Placeholder
        yield f"data: {{'type': 'request_response', 'request_id': '{request_id}'}}\n\n"

    def queue_message_for_client(self, client_id: str, message: dict[str, Any]) -> None:
        """Queue a message to be sent to a specific client.

        Args:
            client_id: Session ID of the target client
            message: JSON-RPC message to send

        Raises:
            ValueError: If client_id is not an active session
        """
        if not self._connection_manager.validate_session(client_id):
            raise ValueError(f"Invalid client session: {client_id}")

        # TODO: Implement message queueing
        # - Add message to client's listening stream queue
        # - Generate event ID for resumability
        # - Store in event history

    async def cleanup_client(self, client_id: str) -> None:
        """Clean up all streams for a disconnected client."""
        if client_id not in self._client_streams:
            return

        # Get all stream IDs for this client
        client_stream_ids = list(self._client_streams[client_id].keys())

        # Clean up each stream individually
        for stream_id in client_stream_ids:
            await self._cleanup_stream(stream_id)

        # Remove client tracking
        self._client_streams.pop(client_id, None)

    async def _cleanup_stream(self, stream_id: str) -> None:
        """Clean up a specific stream."""
        # Clear event tracking for this stream
        self._stream_event_counters.pop(stream_id, None)
        self._stream_event_history.pop(stream_id, None)

        # Find and remove from client tracking
        for client_id, streams in self._client_streams.items():
            if stream_id in streams:
                streams.pop(stream_id, None)
                break

        # TODO: Cancel any background tasks for this stream
        # TODO: Close any open SSE connections for this stream

    def _generate_event_id(self, stream_id: str) -> int:
        """Generate next event ID for a stream (for resumability).

        Args:
            stream_id: ID of the stream to generate an event ID for

        Returns:
            int: Next event ID for this client
        """
        if stream_id not in self._stream_event_counters:
            self._stream_event_counters[stream_id] = 0
        self._stream_event_counters[stream_id] += 1
        return self._stream_event_counters[stream_id]

    async def _replay_stream_events(
        self, stream_id: str, last_event_id: int
    ) -> AsyncIterator[str]:
        """Replay events from a stream after the given event ID.

        Args:
            stream_id: The stream to replay from
            last_event_id: Last event ID the client received

        Yields:
            str: SSE-formatted events that occurred after last_event_id
        """
        if stream_id not in self._stream_event_history:
            # No history for this stream - nothing to replay
            return

        # Get events after the last received event ID
        stream_history = self._stream_event_history[stream_id]

        for event_id, sse_event_data in stream_history:
            if event_id > last_event_id:
                yield sse_event_data

    def _store_event_in_history(
        self, stream_id: str, event_id: int, sse_event_data: str
    ) -> None:
        """Store an event in the stream's history for potential replay.

        Args:
            stream_id: The stream this event belongs to
            event_id: The event ID
            sse_event_data: The complete SSE-formatted event string
        """
        if stream_id not in self._stream_event_history:
            self._stream_event_history[stream_id] = []

        self._stream_event_history[stream_id].append((event_id, sse_event_data))

        # TODO: Implement history size limits to prevent memory growth
        # Could keep last N events, or events from last X minutes, etc.

    def _format_sse_event(self, stream_id: str, data: dict[str, Any]) -> str:
        """Format a message as an SSE event with proper event ID.

        Args:
            stream_id: The stream this event belongs to
            data: Message data to send

        Returns:
            str: SSE-formatted event string with event ID
        """
        import json

        # Generate event ID for this stream
        event_id = self._generate_event_id(stream_id)

        # Format as SSE
        sse_event = f"id: {event_id}\ndata: {json.dumps(data)}\n\n"

        # Store in history for potential replay
        self._store_event_in_history(stream_id, event_id, sse_event)

        return sse_event

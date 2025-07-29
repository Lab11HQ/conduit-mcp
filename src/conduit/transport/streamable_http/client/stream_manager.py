"""Client-side stream management for HTTP transport."""

import asyncio
import json
import logging
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from conduit.transport.client import ServerMessage

logger = logging.getLogger(__name__)


class StreamManager:
    """Manages SSE stream listeners across multiple servers."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        """Initialize stream manager.

        Args:
            http_client: HTTP client to use for SSE connections
        """
        self._http_client = http_client
        # server_id -> set of active listener tasks
        self._server_listeners: dict[str, set[asyncio.Task]] = {}

    async def start_stream_listener(
        self,
        server_id: str,
        response: httpx.Response,
        message_queue: asyncio.Queue[ServerMessage],
    ) -> asyncio.Task:
        """Start listening to an SSE stream from an HTTP response.

        Args:
            server_id: ID of the server this stream belongs to
            response: HTTP response containing the SSE stream
            message_queue: Queue to put parsed messages into

        Returns:
            The asyncio task handling the stream listener
        """
        # Create stream listener task
        task = asyncio.create_task(
            self._listen_to_sse_stream(server_id, response, message_queue),
            name=f"sse-stream-{server_id}",
        )

        # Track task by server
        if server_id not in self._server_listeners:
            self._server_listeners[server_id] = set()

        self._server_listeners[server_id].add(task)

        # Auto-cleanup when task completes
        task.add_done_callback(
            lambda t: self._server_listeners.get(server_id, set()).discard(t)
        )

        logger.debug(f"Started stream listener for server '{server_id}'")
        return task

    def stop_server_listeners(self, server_id: str) -> None:
        """Stop all stream listeners for a specific server.

        Cancels all active listener tasks for the server, which will
        close the underlying SSE connections.

        Args:
            server_id: Server to stop all listeners for
        """
        if server_id not in self._server_listeners:
            return

        listeners = self._server_listeners[server_id].copy()
        cancelled_count = 0

        for task in listeners:
            if not task.done():
                task.cancel()
                cancelled_count += 1

        # Clean up the server entry
        self._server_listeners[server_id].clear()

        if cancelled_count > 0:
            logger.debug(
                f"Cancelled {cancelled_count} stream listeners for server '{server_id}'"
            )

    def get_server_stream_count(self, server_id: str) -> int:
        """Get count of active streams for a server.

        Args:
            server_id: Server to count streams for

        Returns:
            Number of active stream listeners for the server
        """
        if server_id not in self._server_listeners:
            return 0
        return len(
            [task for task in self._server_listeners[server_id] if not task.done()]
        )

    def stop_all_listeners(self) -> None:
        """Stop all stream listeners across all servers."""
        total_cancelled = 0

        for server_id in list(self._server_listeners.keys()):
            listeners = self._server_listeners[server_id].copy()
            for task in listeners:
                if not task.done():
                    task.cancel()
                    total_cancelled += 1
            self._server_listeners[server_id].clear()

        self._server_listeners.clear()

        if total_cancelled > 0:
            logger.debug(
                f"Cancelled {total_cancelled} stream listeners across all servers"
            )

    async def _listen_to_sse_stream(
        self,
        server_id: str,
        response: httpx.Response,
        message_queue: asyncio.Queue[ServerMessage],
    ) -> None:
        """Listen to SSE events from an HTTP response stream.

        Args:
            server_id: Server ID for message attribution
            response: HTTP response containing the SSE stream
            message_queue: Queue to put parsed messages into
        """
        try:
            async with aconnect_sse(
                self._http_client,
                response.request.method,
                str(response.url),
                headers=dict(response.request.headers),
            ) as event_source:
                async for sse_event in event_source.aiter_sse():
                    if sse_event.data:
                        await self._process_sse_event(
                            server_id, sse_event, message_queue
                        )

        except asyncio.CancelledError:
            logger.debug(f"Stream listener for '{server_id}' was cancelled")
            raise
        except Exception as e:
            logger.error(f"Stream listener for '{server_id}' failed: {e}")
        finally:
            logger.debug(f"Stream listener for '{server_id}' closed")

    async def _process_sse_event(
        self,
        server_id: str,
        sse_event: Any,
        message_queue: asyncio.Queue[ServerMessage],
    ) -> None:
        """Process a single SSE event and queue the message.

        Args:
            server_id: Server ID for message attribution
            sse_event: SSE event from httpx-sse
            message_queue: Queue to put the parsed message into
        """
        try:
            message_data = json.loads(sse_event.data)

            server_message = ServerMessage(
                server_id=server_id,
                payload=message_data,
                timestamp=asyncio.get_event_loop().time(),
                metadata={
                    "sse_event_id": sse_event.id,
                }
                if sse_event.id
                else None,
            )

            await message_queue.put(server_message)

            logger.debug(
                f"Server '{server_id}' SSE event: "
                f"{message_data.get('method', 'response')}"
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Server '{server_id}' SSE JSON parse error: {e}")

    @property
    def total_active_streams(self) -> int:
        """Total number of active stream listeners across all servers."""
        return sum(
            len([task for task in listeners if not task.done()])
            for listeners in self._server_listeners.values()
        )

    def __repr__(self) -> str:
        return (
            f"StreamManager(servers={len(self._server_listeners)}, "
            f"active_streams={self.total_active_streams})"
        )

"""Client-side stream management for HTTP transport."""

import asyncio
import json
import logging
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from conduit.transport.client import ServerMessage

logger = logging.getLogger(__name__)


class ClientStreamManager:
    """Manages SSE streams for a single server connection.

    Handles multiple concurrent streams per server, including:
    - Request streams (from POST responses)
    - Server streams (from GET requests)
    - Proper lifecycle management and cleanup
    """

    def __init__(self, server_id: str, http_client: httpx.AsyncClient) -> None:
        """Initialize stream manager for a specific server.

        Args:
            server_id: ID of the server this manager handles
            http_client: HTTP client to use for connections
        """
        self.server_id = server_id
        self._http_client = http_client
        self._active_streams: set[asyncio.Task] = set()
        self._stream_counter = 0

    async def create_response_stream(
        self, response: httpx.Response, message_queue: asyncio.Queue[ServerMessage]
    ) -> None:
        """Create a new SSE stream from an HTTP response.

        Spawns a background task to handle the stream and tracks it for cleanup.

        Args:
            response: HTTP response containing the SSE stream
            message_queue: Queue to put parsed messages into
        """
        self._stream_counter += 1
        stream_id = f"{self.server_id}-response-{self._stream_counter}"

        stream_task = asyncio.create_task(
            self._handle_sse_stream(stream_id, response, message_queue), name=stream_id
        )

        self._active_streams.add(stream_task)
        stream_task.add_done_callback(self._active_streams.discard)

        logger.debug(f"Created response stream {stream_id}")

    async def create_server_stream(
        self,
        endpoint: str,
        headers: dict[str, str],
        message_queue: asyncio.Queue[ServerMessage],
    ) -> None:
        """Create a new server-initiated SSE stream via GET request.

        Args:
            endpoint: Server endpoint URL
            headers: Headers to send with GET request
            message_queue: Queue to put parsed messages into
        """
        self._stream_counter += 1
        stream_id = f"{self.server_id}-server-{self._stream_counter}"

        stream_task = asyncio.create_task(
            self._handle_get_stream(stream_id, endpoint, headers, message_queue),
            name=stream_id,
        )

        self._active_streams.add(stream_task)
        stream_task.add_done_callback(self._active_streams.discard)

        logger.debug(f"Created server stream {stream_id}")

    async def _handle_sse_stream(
        self,
        stream_id: str,
        response: httpx.Response,
        message_queue: asyncio.Queue[ServerMessage],
    ) -> None:
        """Handle an SSE stream from an HTTP response."""
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
                            stream_id, sse_event, message_queue
                        )

        except asyncio.CancelledError:
            logger.debug(f"Stream {stream_id} was cancelled")
            raise
        except Exception as e:
            logger.error(f"Stream {stream_id} error: {e}")
        finally:
            logger.debug(f"Stream {stream_id} closed")

    async def _handle_get_stream(
        self,
        stream_id: str,
        endpoint: str,
        headers: dict[str, str],
        message_queue: asyncio.Queue[ServerMessage],
    ) -> None:
        """Handle a server-initiated SSE stream via GET request."""
        try:
            async with self._http_client.stream(
                "GET", endpoint, headers=headers
            ) as response:
                if response.status_code != 200:
                    logger.warning(
                        f"GET stream {stream_id} failed: {response.status_code}"
                    )
                    return

                if "text/event-stream" not in response.headers.get("content-type", ""):
                    logger.warning(
                        f"GET stream {stream_id} not SSE: "
                        f"{response.headers.get('content-type')}"
                    )
                    return

                async with aconnect_sse(
                    self._http_client, "GET", endpoint, headers=headers
                ) as event_source:
                    async for sse_event in event_source.aiter_sse():
                        if sse_event.data:
                            await self._process_sse_event(
                                stream_id, sse_event, message_queue
                            )

        except asyncio.CancelledError:
            logger.debug(f"GET stream {stream_id} was cancelled")
            raise
        except Exception as e:
            logger.error(f"GET stream {stream_id} error: {e}")
        finally:
            logger.debug(f"GET stream {stream_id} closed")

    async def _process_sse_event(
        self,
        stream_id: str,
        sse_event: Any,
        message_queue: asyncio.Queue[ServerMessage],
    ) -> None:
        """Process a single SSE event and queue the message."""
        try:
            message_data = json.loads(sse_event.data)

            server_message = ServerMessage(
                server_id=self.server_id,
                payload=message_data,
                timestamp=asyncio.get_event_loop().time(),
                metadata={
                    "stream_id": stream_id,
                    "sse_event_id": sse_event.id,
                }
                if sse_event.id
                else {"stream_id": stream_id},
            )

            await message_queue.put(server_message)

            logger.debug(
                f"Stream {stream_id} received: {message_data.get('method', 'response')}"
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Stream {stream_id} JSON parse error: {e}")

    def cancel_all_streams(self) -> None:
        """Cancel all active streams for this server."""
        if not self._active_streams:
            return

        cancelled_count = 0
        for stream_task in list(self._active_streams):
            if not stream_task.done():
                stream_task.cancel()
                cancelled_count += 1

        if cancelled_count > 0:
            logger.debug(
                f"Cancelled {cancelled_count} streams for server {self.server_id}"
            )

    @property
    def active_stream_count(self) -> int:
        """Number of currently active streams."""
        return len([task for task in self._active_streams if not task.done()])

    def __repr__(self) -> str:
        return (
            f"ClientStreamManager(server_id={self.server_id}, "
            f"active_streams={self.active_stream_count})"
        )

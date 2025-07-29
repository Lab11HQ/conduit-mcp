import asyncio
import json
import logging
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

    async def close(self) -> None:
        """Explicitly close the stream."""
        # Send sentinel to stop the generator
        await self._message_queue.put({"__close__": True})
        logger.debug(f"Manually closed stream {self.stream_id}")

    def is_response(self, message: dict[str, Any]) -> bool:
        """Check if message is a JSON-RPC response."""
        id_value = message.get("id")
        has_valid_id = (
            id_value is not None
            and isinstance(id_value, (int, str))
            and not isinstance(id_value, bool)
        )
        has_result = "result" in message
        has_error = "error" in message
        return has_valid_id and (has_result ^ has_error)

    async def event_generator(self) -> AsyncIterator[str]:
        """Generate SSE events for this stream.

        Automatically closes after sending a response.

        Yields:
            str: SSE event data
        """
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

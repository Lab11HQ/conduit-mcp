from collections.abc import AsyncIterator
from typing import Any

import httpx

from conduit.transport.base import Transport, TransportMessage
from conduit.transport.http.client.client_message_sender import ClientMessageSender
from conduit.transport.http.client.client_stream_manager import ClientStreamManager


class HTTPClientTransport(Transport):
    """HTTP transport for MCP clients.

    Coordinates MessageSender and StreamManager to provide a unified
    Transport interface for HTTP-based MCP communication.
    """

    def __init__(self, endpoint_url: str, http_client: httpx.AsyncClient | None = None):
        self._endpoint_url = endpoint_url
        self._http_client = http_client or httpx.AsyncClient()
        self._owns_http_client = http_client is None

        # Component coordination
        self._stream_manager = ClientStreamManager(endpoint_url, self._http_client)
        self._message_sender = ClientMessageSender(
            endpoint_url, self._http_client, self._stream_manager
        )

        # Transport state
        self._started = False
        self._closed = False

    @property
    def is_open(self) -> bool:
        """True if the transport is open and ready for message processing."""
        return self._started and not self._closed

    async def send(self, payload: dict[str, Any]) -> None:
        """Send a message to the server.

        Routes to appropriate handler based on JSON-RPC message type.

        Args:
            payload: JSON-RPC message to send

        Raises:
            ConnectionError: If transport is closed or connection failed
            ValueError: If message format is invalid
        """
        if self._closed:
            raise ConnectionError("Transport is closed")

        # Ensure transport is started
        await self._ensure_started()

        # Route based on JSON-RPC message type
        if self._is_notification(payload):
            await self._message_sender.send_notification(payload)

        elif self._is_response(payload):
            await self._message_sender.send_response(payload)

        elif self._is_request(payload):
            # Handle immediate responses by injecting into stream
            result = await self._message_sender.send_request(payload)
            if result is not None:
                # Immediate JSON response - inject into stream manager
                transport_message = TransportMessage(
                    payload=result,
                    metadata={
                        "source": "immediate_response",
                        "request_id": payload.get("id"),
                        "endpoint_url": self._endpoint_url,
                    },
                )
                await self._stream_manager._inject_immediate_response(transport_message)

        else:
            raise ValueError(f"Invalid JSON-RPC message format: {payload}")

    def messages(self) -> AsyncIterator[TransportMessage]:
        """Stream of incoming messages from the server.

        Yields messages from all active streams (listening + request streams).

        Yields:
            TransportMessage: Each incoming message with metadata

        Raises:
            ConnectionError: When transport connection fails
            asyncio.CancelledError: When iteration is cancelled
        """
        if self._closed:
            raise ConnectionError("Transport is closed")

        return self._stream_manager.messages()

    async def close(self) -> None:
        """Close the transport and stop all message processing."""
        if self._closed:
            return

        self._closed = True

        # Close components in reverse order
        await self._stream_manager.close()

        # Close HTTP client if we own it
        if self._owns_http_client:
            await self._http_client.aclose()

    async def _ensure_started(self) -> None:
        """Ensure transport is started and listening stream is active."""
        if self._started:
            return

        # Start listening stream for server-initiated messages
        listening_stream_id = await self._stream_manager.start_listening_stream()
        if listening_stream_id is None:
            raise ConnectionError("Failed to start listening stream")

        self._started = True

    def _is_notification(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a JSON-RPC notification."""
        return (
            "method" in payload
            and "id" not in payload
            and "result" not in payload
            and "error" not in payload
        )

    def _is_response(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a JSON-RPC response."""
        return (
            "id" in payload
            and ("result" in payload or "error" in payload)
            and "method" not in payload
        )

    def _is_request(self, payload: dict[str, Any]) -> bool:
        """Check if payload is a JSON-RPC request."""
        return (
            "method" in payload
            and "id" in payload
            and "result" not in payload
            and "error" not in payload
        )

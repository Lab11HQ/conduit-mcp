"""Streamable HTTP client transport implementation."""

import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

from conduit.transport.client import ClientTransport, ServerMessage

logger = logging.getLogger(__name__)


class StreamableHttpClientTransport(ClientTransport):
    """HTTP client transport supporting multiple server connections.

    Phase 1: Basic HTTP POST/JSON response with session management.
    Future phases will add SSE streams, resumability, etc.
    """

    def __init__(self) -> None:
        """Initialize HTTP client transport."""
        self._servers: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, str] = {}  # server_id -> session_id
        self._http_client = httpx.AsyncClient()
        self._message_queue: asyncio.Queue[ServerMessage] = asyncio.Queue()

    async def add_server(self, server_id: str, connection_info: dict[str, Any]) -> None:
        """Register HTTP server endpoint.

        Args:
            server_id: Unique identifier for this server connection
            connection_info: HTTP connection details
                Expected keys:
                - "endpoint": str - HTTP endpoint URL (e.g., "https://example.com/mcp")
                - "headers": dict[str, str] - Additional HTTP headers (optional)

        Raises:
            ValueError: If connection_info is invalid
        """
        if "endpoint" not in connection_info:
            raise ValueError("connection_info must contain 'endpoint' key")

        endpoint = connection_info["endpoint"]
        if not isinstance(endpoint, str) or not endpoint.startswith(
            ("http://", "https://")
        ):
            raise ValueError("'endpoint' must be a valid HTTP URL")

        # Store server configuration
        self._servers[server_id] = {
            "endpoint": endpoint,
            "headers": connection_info.get("headers", {}),
        }

        logger.debug(f"Registered server '{server_id}' with endpoint: {endpoint}")

    async def send(self, server_id: str, message: dict[str, Any]) -> None:
        """Send message to server via HTTP POST.

        Phase 1: Always expects immediate JSON response.

        Args:
            server_id: Target server connection ID
            message: JSON-RPC message to send

        Raises:
            ValueError: If server_id is not registered
            ConnectionError: If HTTP request fails
        """
        if server_id not in self._servers:
            raise ValueError(f"Server '{server_id}' is not registered")

        server_config = self._servers[server_id]
        endpoint = server_config["endpoint"]

        # Build headers
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",  # TODO: Make configurable
            **server_config["headers"],
        }

        # Add session ID if we have one
        if server_id in self._sessions:
            headers["Mcp-Session-Id"] = self._sessions[server_id]

        try:
            response = await self._http_client.post(
                endpoint,
                json=message,
                headers=headers,
                timeout=30.0,  # TODO: Make configurable
            )

            # Handle session management
            await self._handle_session_management(server_id, message, response)

            # Handle response
            if response.status_code == 200:
                response_data = response.json()
                # Put response in queue for server_messages()
                server_message = ServerMessage(
                    server_id=server_id,
                    payload=response_data,
                    timestamp=asyncio.get_event_loop().time(),
                )
                await self._message_queue.put(server_message)

            elif response.status_code == 404:
                # Session expired - clear session ID
                if server_id in self._sessions:
                    del self._sessions[server_id]
                raise ConnectionError(f"Session expired for server '{server_id}'")

            else:
                response.raise_for_status()

        except httpx.RequestError as e:
            raise ConnectionError(
                f"HTTP request failed for server '{server_id}': {e}"
            ) from e

    async def _handle_session_management(
        self, server_id: str, message: dict[str, Any], response: httpx.Response
    ) -> None:
        """Handle session ID extraction from InitializeResult."""
        # Check if this was an InitializeRequest and response contains session ID
        if (
            message.get("method") == "initialize"
            and response.status_code == 200
            and "Mcp-Session-Id" in response.headers
        ):
            session_id = response.headers["Mcp-Session-Id"]
            self._sessions[server_id] = session_id
            logger.debug(f"Stored session ID for server '{server_id}': {session_id}")

    def server_messages(self) -> AsyncIterator[ServerMessage]:
        """Stream of messages from all servers.

        Phase 1: Simple queue-based approach.
        """
        return self._message_queue_iterator()

    async def _message_queue_iterator(self) -> AsyncIterator[ServerMessage]:
        """Async iterator that yields messages from the queue."""
        while True:
            try:
                message = await self._message_queue.get()
                yield message
            except Exception as e:
                logger.error(f"Error reading from message queue: {e}")
                break

    async def disconnect_server(self, server_id: str) -> None:
        """Disconnect from specific server.

        Args:
            server_id: Server connection ID to disconnect
        """
        if server_id not in self._servers:
            return

        # If we have a session, try to terminate it gracefully
        if server_id in self._sessions:
            try:
                session_id = self._sessions[server_id]
                endpoint = self._servers[server_id]["endpoint"]
                headers = {"Mcp-Session-Id": session_id}

                # Attempt graceful session termination
                await self._http_client.delete(endpoint, headers=headers, timeout=5.0)

            except Exception as e:
                logger.debug(
                    f"Failed to gracefully terminate session for '{server_id}': {e}"
                )
            finally:
                del self._sessions[server_id]

        # Remove server configuration
        del self._servers[server_id]
        logger.debug(f"Disconnected from server '{server_id}'")

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup HTTP client."""
        await self._http_client.aclose()

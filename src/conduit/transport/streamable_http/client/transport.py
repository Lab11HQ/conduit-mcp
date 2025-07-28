"""Streamable HTTP client transport implementation."""

import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

from conduit.protocol.base import PROTOCOL_VERSION
from conduit.transport.client import ClientTransport, ServerMessage
from conduit.transport.streamable_http.client.stream_manager import StreamManager

logger = logging.getLogger(__name__)


class HttpClientTransport(ClientTransport):
    """HTTP client transport supporting multiple server connections.

    Implements the Streamable HTTP transport specification, supporting:
    - HTTP POST for sending messages to servers
    - SSE streams for receiving messages from servers
    - Session management with Mcp-Session-Id headers
    - Multiple concurrent server connections
    """

    def __init__(self) -> None:
        """Initialize HTTP client transport."""
        self._servers: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, str] = {}  # server_id -> session_id
        self._http_client = httpx.AsyncClient()
        self._message_queue: asyncio.Queue[ServerMessage] = asyncio.Queue()
        # server_id -> stream manager
        self._stream_managers: dict[str, StreamManager] = {}

    async def add_server(self, server_id: str, connection_info: dict[str, Any]) -> None:
        """Register HTTP server endpoint.

        Stores the server configuration without establishing a connection.
        Connection will be established when first message is sent.

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

        All JSON-RPC messages are sent as HTTP POST requests to the MCP endpoint.
        Handles both immediate JSON responses and SSE streams according to the spec.

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
        headers = self._build_headers(server_id, server_config)

        try:
            response = await self._http_client.post(
                endpoint,
                json=message,
                headers=headers,
                timeout=30.0,  # TODO: Make configurable
            )

            # Handle session management for initialize responses
            await self._handle_session_management(server_id, message, response)

            # Handle different response types based on content-type
            await self._handle_response(server_id, response)

        except httpx.RequestError as e:
            raise ConnectionError(
                f"HTTP request failed for server '{server_id}': {e}"
            ) from e

    async def _handle_response(self, server_id: str, response: httpx.Response) -> None:
        """Handle the HTTP response based on content type and status.

        According to the spec:
        - 200 with application/json: Single JSON response
        - 200 with text/event-stream: SSE stream
        - 202: Accepted (for notifications/responses)
        - 404: Session expired (if we sent a session ID)
        - Other errors: Raise ConnectionError

        Args:
            server_id: Server ID to handle response for
            response: The HTTP response from the server

        Raises:
            ConnectionError: If the session expired or other HTTP errors
        """
        if response.status_code == 200:
            content_type = response.headers.get("content-type", "")

            if "application/json" in content_type:
                response_data = response.json()
                server_message = ServerMessage(
                    server_id=server_id,
                    payload=response_data,
                    timestamp=asyncio.get_event_loop().time(),
                )
                await self._message_queue.put(server_message)

            elif "text/event-stream" in content_type:
                # Get or create stream manager for this server
                if server_id not in self._stream_managers:
                    self._stream_managers[server_id] = StreamManager(
                        server_id, self._http_client
                    )

                stream_manager = self._stream_managers[server_id]
                await stream_manager.create_response_stream(
                    response, self._message_queue
                )

        elif response.status_code == 202:
            logger.debug(f"Server '{server_id}' accepted message (202)")

        elif response.status_code == 404:
            # Check if we sent a session ID - if so, this means session expired
            request_had_session = "Mcp-Session-Id" in response.request.headers

            if request_had_session:
                # Session expired - clear session ID per spec
                if server_id in self._sessions:
                    expired_session = self._sessions[server_id]
                    del self._sessions[server_id]
                    logger.info(
                        f"Session '{expired_session}' expired for server '{server_id}'"
                        " - cleared session ID"
                    )

                raise ConnectionError(
                    f"Session expired for server '{server_id}'. "
                    "Must re-initialize with a new InitializeRequest."
                )
            else:
                # Regular 404 - not session related
                raise ConnectionError(
                    f"Server '{server_id}' returned 404: {response.text or 'Not Found'}"
                )

        else:
            # Other HTTP errors
            response.raise_for_status()

    async def _handle_session_management(
        self, server_id: str, message: dict[str, Any], response: httpx.Response
    ) -> None:
        """Handle session ID extraction from InitializeResult responses.

        According to the spec, servers MAY include an Mcp-Session-Id header
        in the response to an initialize request to establish a session.

        Args:
            server_id: Server ID to handle session management for
            message: The message that was sent to the server
            response: The response from the server
        """
        if (
            message.get("method") == "initialize"
            and response.status_code == 200
            and "Mcp-Session-Id" in response.headers
        ):
            session_id = response.headers["Mcp-Session-Id"]
            self._sessions[server_id] = session_id
            logger.debug(f"Established session for server '{server_id}': {session_id}")

    async def disconnect_server(self, server_id: str) -> None:
        """Disconnect from specific server.

        Attempts graceful session termination via DELETE request if we have a session,
        cancels all active SSE streams, then cleans up all local state.
        Safe to call multiple times.

        Args:
            server_id: Server connection ID to disconnect
        """
        if server_id not in self._servers:
            return

        # Cancel all streams for this server
        if server_id in self._stream_managers:
            self._stream_managers[server_id].cancel_all_streams()
            del self._stream_managers[server_id]

        # If we have a session, try to terminate it gracefully
        if server_id in self._sessions:
            try:
                session_id = self._sessions[server_id]
                endpoint = self._servers[server_id]["endpoint"]

                # Build headers for DELETE request
                headers = {
                    "Mcp-Session-Id": session_id,
                    "MCP-Protocol-Version": PROTOCOL_VERSION,
                }
                # Add any custom headers from server config
                headers.update(self._servers[server_id]["headers"])

                # Attempt graceful session termination
                response = await self._http_client.delete(
                    endpoint, headers=headers, timeout=5.0
                )

                if response.status_code == 200:
                    logger.debug(
                        f"Successfully terminated session '{session_id}' for "
                        f"server '{server_id}'"
                    )
                elif response.status_code == 405:
                    logger.debug(
                        f"Server '{server_id}' does not support session termination "
                        "(405)"
                    )
                else:
                    logger.warning(
                        f"Unexpected response {response.status_code} when terminating "
                        f"session for '{server_id}'"
                    )

            except Exception as e:
                logger.debug(
                    f"Failed to gracefully terminate session for '{server_id}': {e}"
                )
            finally:
                # Always clean up session state
                del self._sessions[server_id]

        # Remove server configuration
        del self._servers[server_id]
        logger.debug(f"Disconnected from server '{server_id}'")

    async def close(self) -> None:
        """Close the HTTP client and clean up all resources.

        Cancels all active streams and closes the underlying HTTP client.
        Safe to call multiple times.
        """
        # Cancel all active streams across all servers
        for stream_manager in list(self._stream_managers.values()):
            stream_manager.cancel_all_streams()
        self._stream_managers.clear()

        # Clear all state
        self._servers.clear()
        self._sessions.clear()

        # Close the HTTP client
        if not self._http_client.is_closed:
            await self._http_client.aclose()
            logger.debug("HTTP client closed")

    def _build_headers(
        self, server_id: str, server_config: dict[str, Any]
    ) -> dict[str, str]:
        """Build HTTP headers for requests to the server.

        Constructs headers according to the Streamable HTTP spec:
        - Content-Type: application/json (for POST body)
        - Accept: application/json, text/event-stream (support both response types)
        - MCP-Protocol-Version: current protocol version
        - Mcp-Session-Id: session ID if we have one for this server
        - Any custom headers from server config

        Args:
            server_id: Server ID to build headers for
            server_config: Server configuration containing custom headers

        Returns:
            Complete headers dict for the HTTP request
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }

        # Add session ID if we have one for this server
        if server_id in self._sessions:
            headers["Mcp-Session-Id"] = self._sessions[server_id]

        # Add any custom headers from server config
        headers.update(server_config["headers"])

        return headers

    async def start_server_stream(self, server_id: str) -> None:
        """Start a server-initiated message stream via HTTP GET.

        Opens an SSE stream that allows the server to send requests and
        notifications without the client first sending a message.

        Args:
            server_id: Server to start stream for

        Raises:
            ValueError: If server_id is not registered
            ConnectionError: If the server doesn't support server streams (405)
                or other HTTP errors occur
        """
        if server_id not in self._servers:
            raise ValueError(f"Server '{server_id}' is not registered")

        server_config = self._servers[server_id]
        endpoint = server_config["endpoint"]

        # Build headers for GET request - only Accept text/event-stream
        headers = {
            "Accept": "text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }

        # Add session ID if we have one
        if server_id in self._sessions:
            headers["Mcp-Session-Id"] = self._sessions[server_id]

        # Add custom headers from server config
        headers.update(server_config["headers"])

        try:
            # Test if server supports GET streams
            response = await self._http_client.get(
                endpoint,
                headers=headers,
                timeout=10.0,  # Shorter timeout for initial connection
            )

            if response.status_code == 405:
                raise ConnectionError(
                    f"Server '{server_id}' does not support server-initiated streams "
                    "(405)"
                )
            elif response.status_code == 404:
                # Handle session expiry same as in _handle_response
                if "Mcp-Session-Id" in headers:
                    if server_id in self._sessions:
                        expired_session = self._sessions[server_id]
                        del self._sessions[server_id]
                        logger.info(
                            f"Session '{expired_session}' expired for server "
                            f"'{server_id}' during GET stream setup - cleared session "
                            "ID"
                        )
                    raise ConnectionError(
                        f"Session expired for server '{server_id}'. "
                        "Must re-initialize with a new InitializeRequest."
                    )
                else:
                    raise ConnectionError(
                        f"Server '{server_id}' returned 404 for GET stream"
                    )
            elif response.status_code != 200:
                response.raise_for_status()

            # Check content type
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" not in content_type:
                raise ConnectionError(
                    f"Server '{server_id}' returned non-SSE content type: "
                    f"{content_type}"
                )

            # Create stream manager if needed and start the server stream
            if server_id not in self._stream_managers:
                self._stream_managers[server_id] = StreamManager(
                    server_id, self._http_client
                )

            stream_manager = self._stream_managers[server_id]
            await stream_manager.create_server_stream(
                endpoint, headers, self._message_queue
            )

            logger.debug(f"Started server stream for '{server_id}'")

        except Exception as e:
            if isinstance(e, ConnectionError):
                raise
            raise ConnectionError(
                f"Failed to start server stream for '{server_id}': {e}"
            ) from e

    def server_messages(self) -> AsyncIterator[ServerMessage]:
        """Stream of messages from all servers with explicit server context.

        Yields messages from the internal queue as they arrive from HTTP responses
        and SSE streams. This is the main way consumers get messages from servers.

        Yields:
            ServerMessage: Message with server ID and metadata
        """
        return self._message_queue_iterator()

    async def _message_queue_iterator(self) -> AsyncIterator[ServerMessage]:
        """Async iterator that yields messages from the queue.

        Continuously reads from the message queue until the transport is closed.
        This runs indefinitely - consumers should break out of the loop when done.
        """
        while True:
            try:
                message = await self._message_queue.get()
                yield message
            except Exception as e:
                logger.error(f"Error reading from message queue: {e}")
                break

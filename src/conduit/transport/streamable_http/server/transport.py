"""Streamable HTTP server transport implementation.

This module implements the MCP Streamable HTTP transport server, supporting:
- Multiple concurrent client connections
- Session management with secure session IDs
- SSE streams for request/response cycles
- Server-initiated message delivery
- Full spec compliance with proper validation

Architecture:
    - SessionManager: Handles session lifecycle and validation
    - StreamManager: Manages SSE streams and message routing
    - MessageParser: Validates JSON-RPC message structure
    - Main transport: Orchestrates HTTP handling and message flow
"""

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from conduit.protocol.base import PROTOCOL_VERSION
from conduit.shared.message_parser import MessageParser
from conduit.transport.server import ClientMessage, ServerTransport, TransportContext
from conduit.transport.streamable_http.server.session_manager import SessionManager
from conduit.transport.streamable_http.server.stream_manager import StreamManager

logger = logging.getLogger(__name__)


class HttpServerTransport(ServerTransport):
    """HTTP server transport supporting multiple client connections.

    Implements the MCP Streamable HTTP transport specification with:
    - Always-assigned session IDs for simplified protocol handling
    - Immediate 202 responses for notifications and responses
    - SSE streams for requests with auto-cleanup after responses
    - Server-initiated message streams via GET endpoint

    Message Flow:
        1. POST /mcp → Validate → Route by type → Stream/202 response
        2. GET /mcp → Validate session → Create server stream
        3. DELETE /mcp → Terminate session

    Stream Types:
        - Request streams: client:request:123 (ephemeral, auto-close)
        - Server streams: client:server:abc (persistent, server-initiated)
    """

    def __init__(
        self, endpoint_path: str = "/mcp", host: str = "127.0.0.1", port: int = 8000
    ) -> None:
        """Initialize HTTP server transport."""
        self.endpoint_path = endpoint_path
        self.host = host
        self.port = port

        # Core managers - will inject these in the future as needed
        self._session_manager = SessionManager()
        self._stream_manager = StreamManager()

        # Message parser - always default
        self._message_parser = MessageParser()

        # Message queue for client messages
        self._message_queue: asyncio.Queue[ClientMessage] = asyncio.Queue()

        # HTTP server setup
        self._app = Starlette(
            routes=[
                Route(
                    endpoint_path,
                    self._handle_mcp_endpoint,
                    methods=["POST", "GET", "DELETE"],
                )
            ]
        )
        self._server = None

    # ================================
    # Lifecycle
    # ================================

    async def start(self) -> None:
        """Start the HTTP server."""
        config = uvicorn.Config(
            app=self._app, host=self.host, port=self.port, log_level="info"
        )
        self._server = uvicorn.Server(config)

        # Start server in background task
        asyncio.create_task(self._server.serve())
        logger.info(
            f"HTTP server started on {self.host}:{self.port}{self.endpoint_path}"
        )

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._server:
            self._server.should_exit = True
            await self._server.shutdown()

    # ================================
    # Server Transport Interface
    # ================================

    async def send(
        self,
        client_id: str,
        message: dict[str, Any],
        transport_context: TransportContext | None = None,
    ) -> None:
        """Send message to specific client.

        Args:
            client_id: Target client connection ID
            message: JSON-RPC message to send
            transport_context: Context for the transport. For example, this helps route
                messages along specific streams.

        Raises:
            ValueError: If client_id is not connected
            ConnectionError: If connection failed during send
        """
        if not self._session_manager.get_session_id(client_id):
            raise ValueError(f"Client {client_id} is not connected")

        originating_request_id = (
            transport_context.originating_request_id if transport_context else None
        )

        if await self._stream_manager.send_to_existing_stream(
            client_id, message, originating_request_id
        ):
            return

        raise ConnectionError(f"No active streams available for client {client_id}")

    def client_messages(self) -> AsyncIterator[ClientMessage]:
        """Stream of messages from all clients."""
        return self._message_queue_iterator()

    async def disconnect_client(self, client_id: str) -> None:
        """Disconnect specific client."""
        session_id = self._session_manager.get_session_id(client_id)
        if session_id:
            self._session_manager.terminate_session(session_id)

    async def close(self) -> None:
        """Close the transport and clean up all resources.

        For HTTP transport, this stops the HTTP server and cleans up all sessions.
        Safe to call multiple times.
        """
        await self.stop()

        # Clean up sessions and streams
        self._session_manager.terminate_all_sessions()
        await self._stream_manager.close_all_streams()

    # ================================
    # HTTP Request Handlers
    # ================================

    async def _handle_mcp_endpoint(self, request: Request) -> Response:
        """Handle MCP endpoint requests with clean routing."""
        try:
            if request.method == "POST":
                return await self._handle_post_request(request)
            elif request.method == "GET":
                return await self._handle_get_request(request)
            elif request.method == "DELETE":
                return await self._handle_delete_request(request)
            else:
                return Response("Method not allowed", status_code=405)

        except Exception as e:
            logger.error(f"Error handling MCP request: {e}")
            return Response("Internal server error", status_code=500)

    async def _handle_post_request(self, request: Request) -> Response:
        """Handle HTTP POST request with JSON-RPC message."""
        headers_error = self._validate_protocol_headers(request)
        if headers_error:
            return headers_error

        try:
            message_data = await request.json()
            if not isinstance(message_data, dict):
                return Response(
                    f"Invalid JSON: expected object, got {type(message_data).__name__}",
                    status_code=400,
                )
        except json.JSONDecodeError as e:
            return Response(
                f"Invalid JSON: {e.msg} at position {e.pos}", status_code=400
            )

        jsonrpc_error = self._validate_jsonrpc_message(message_data)
        if jsonrpc_error:
            return jsonrpc_error

        session_error = self._validate_session(request, message_data)
        if session_error:
            return session_error

        try:
            client_id, session_id = await self._get_or_create_client(
                request, message_data
            )
        except ValueError as e:
            return Response(str(e), status_code=500)

        client_message = ClientMessage(
            client_id=client_id,
            payload=message_data,
            timestamp=time.time(),
        )
        await self._message_queue.put(client_message)

        response_headers = self._build_response_headers(request, session_id)

        if self._is_mcp_request(message_data):
            request_id = message_data["id"]
            return await self._create_request_stream(
                client_id, request_id, response_headers
            )
        else:
            return Response(status_code=202, headers=response_headers)

    async def _handle_get_request(self, request: Request) -> Response:
        """Handle HTTP GET request for SSE streams."""
        headers_error = self._validate_protocol_headers(request)
        if headers_error:
            return headers_error

        session_id = request.headers.get("Mcp-Session-Id")
        if not session_id:
            return Response("Missing session ID", status_code=400)

        client_id = self._session_manager.get_client_id(session_id)
        if not client_id:
            return Response("Invalid or expired session", status_code=404)

        headers = self._build_server_stream_headers(request, session_id)

        try:
            stream = await self._stream_manager.create_stream(client_id)
            logger.debug(
                f"Created server stream {stream.stream_id} for client {client_id}"
            )

            return StreamingResponse(
                stream.event_generator(),
                media_type="text/event-stream",
                headers=headers,
            )
        except Exception as e:
            logger.error(f"Failed to create server stream for client {client_id}: {e}")
            return Response("Internal server error", status_code=500)

    async def _handle_delete_request(self, request: Request) -> Response:
        """Handle session termination."""
        session_id = request.headers.get("Mcp-Session-Id")
        if not session_id:
            return Response("Missing session ID", status_code=400)

        if not self._session_manager.terminate_session(session_id):
            return Response("Session not found", status_code=404)

        return Response(status_code=200)

    # ================================
    # Validation Helpers
    # ================================

    def _validate_protocol_headers(self, request: Request) -> Response | None:
        """Validate required MCP protocol headers (Protocol-Version, Accept, Origin)."""
        protocol_version = request.headers.get("MCP-Protocol-Version")
        if not protocol_version:
            return Response(
                f"Missing MCP-Protocol-Version header, expected: {PROTOCOL_VERSION}",
                status_code=400,
            )
        elif protocol_version != PROTOCOL_VERSION:
            return Response(
                f"Invalid MCP-Protocol-Version: {protocol_version}, expected:"
                f" {PROTOCOL_VERSION}",
                status_code=400,
            )

        accept = request.headers.get("Accept")
        if not accept:
            return Response(
                "Missing Accept header, expected: text/event-stream, application/json",
                status_code=400,
            )
        if "text/event-stream" not in accept or "application/json" not in accept:
            return Response(
                "Invalid Accept header, expected: text/event-stream, application/json"
                f" (got: {accept})",
                status_code=400,
            )

        # TODO: Implement proper Origin validation to prevent DNS rebinding attacks
        # For now, we accept all origins (development mode)
        origin = request.headers.get("Origin")
        if not self._is_valid_origin(origin):
            logger.warning(f"Invalid Origin header: {origin}")
            return Response("Invalid Origin header", status_code=400)

        return None

    def _validate_session(
        self, request: Request, message_data: dict
    ) -> Response | None:
        """Validate session ID requirements for MCP requests.

        Returns None if session requirements are met, otherwise returns an error
        response.
        """
        session_id = request.headers.get("Mcp-Session-Id")
        is_initialize = (
            self._is_mcp_request(message_data)
            and message_data.get("method") == "initialize"
        )

        if is_initialize:
            # Initialize requests should NOT have a session ID
            if session_id:
                return Response(
                    "Initialize request must not include session ID", status_code=400
                )
            return None
        else:
            # All other messages MUST have a valid session ID
            if not session_id:
                return Response("Missing Mcp-Session-Id header", status_code=400)
            if not self._session_manager.session_exists(session_id):
                return Response("Invalid or expired Mcp-Session-Id", status_code=404)
            return None

    def _validate_jsonrpc_message(self, message_data: dict) -> Response | None:
        """Validate JSON-RPC message structure.

        Returns None if valid, otherwise returns an error response.
        """
        is_request = self._message_parser.is_valid_request(message_data)
        is_response = self._message_parser.is_valid_response(message_data)
        is_notification = self._message_parser.is_valid_notification(message_data)

        if not (is_request or is_response or is_notification):
            return Response(
                f"Invalid JSON-RPC message: {message_data}", status_code=400
            )
        return None

    def _is_valid_origin(self, origin: str | None) -> bool:
        """Validate Origin header to prevent DNS rebinding attacks.

        TODO: Implement proper origin validation based on configuration.
        For now, accepts all origins for development.
        """
        # Stub implementation - accept all origins
        # In production, this should validate against:
        # - Configured allowed origins
        # - Same-origin policy
        # - Trusted domain list
        return True

    # ================================
    # Session and client management
    # ================================

    async def _get_or_create_client(
        self, request: Request, message_data: dict
    ) -> tuple[str, str]:
        """Get existing client or create new session for initialize requests.

        Returns:
            Tuple of (client_id, session_id)

        Raises:
            ValueError: If missing session ID or client not found
        """
        session_id = request.headers.get("Mcp-Session-Id")
        is_initialize = (
            self._is_mcp_request(message_data)
            and message_data.get("method") == "initialize"
        )

        if is_initialize:
            client_id, session_id = self._session_manager.create_session()
            return client_id, session_id
        else:
            if session_id is None:
                raise ValueError("Session ID is required for non-initialize requests")

            client_id = self._session_manager.get_client_id(session_id)
            if not client_id:
                raise ValueError("Client not found for session")
            return client_id, session_id

    # ================================
    # Stream Management
    # ================================

    async def _create_request_stream(
        self, client_id: str, request_id: str | int, headers: dict[str, str]
    ) -> StreamingResponse | Response:
        """Create SSE stream for a request.

        The stream will:
        1. Send any server-initiated messages (requests/notifications)
        2. Send the final response to the original request
        3. Auto-close after sending the response
        """
        try:
            stream = await self._stream_manager.create_stream(client_id, request_id)

            return StreamingResponse(
                stream.event_generator(),
                media_type="text/event-stream",
                headers=headers,
            )
        except Exception as e:
            logger.error(f"Failed to create request stream for client {client_id}: {e}")
            return Response("Internal server error", status_code=500)

    # ================================
    # Response Builders
    # ================================

    def _build_response_headers(
        self, request: Request, session_id: str
    ) -> dict[str, str]:
        """Build standard response headers."""
        return {
            "Access-Control-Allow-Origin": request.headers.get("Origin", "*"),
            "Cache-Control": "no-cache",
            "Mcp-Session-Id": session_id,
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }

    def _build_server_stream_headers(
        self, request: Request, session_id: str
    ) -> dict[str, str]:
        """Build headers for server stream responses."""
        return {
            "Access-Control-Allow-Origin": request.headers.get("Origin", "*"),
            "Cache-Control": "no-cache",
            "Content-Type": "text/event-stream",
            "Connection": "keep-alive",
            "Mcp-Session-Id": session_id,
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }

    # ================================
    # Utility methods
    # ================================

    def _is_mcp_request(self, message_data: dict[str, Any]) -> bool:
        """Check if message is an MCP request (has method field and id)."""
        return self._message_parser.is_valid_request(message_data)

    async def _message_queue_iterator(self) -> AsyncIterator[ClientMessage]:
        """Async iterator that yields messages from the queue."""
        while True:
            try:
                message = await self._message_queue.get()
                yield message
            except Exception as e:
                logger.error(f"Error reading from message queue: {e}")
                break

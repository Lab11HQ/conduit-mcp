"""Streamable HTTP server transport implementation."""

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
from conduit.transport.streamable_http.session_manager import SessionManager
from conduit.transport.streamable_http.streams import StreamManager

logger = logging.getLogger(__name__)


class StreamableHttpServerTransport(ServerTransport):
    """HTTP server transport supporting multiple client connections.

    Implements the streamable HTTP transport with:
    - Always-assigned session IDs for simplified protocol handling
    - Immediate 202 responses for notifications and responses
    - SSE streams for requests (future phase)
    - Full resumability support (future phase)
    """

    def __init__(
        self, endpoint_path: str = "/mcp", host: str = "127.0.0.1", port: int = 8000
    ) -> None:
        """Initialize HTTP server transport."""
        self.endpoint_path = endpoint_path
        self.host = host
        self.port = port

        # Core managers
        self._session_manager = SessionManager()
        self._stream_manager = StreamManager()
        self._message_parser = MessageParser()  # Add message parser
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
        # Validate HTTP protocol headers
        if not self._has_valid_protocol_headers(request):
            return Response("Bad request", status_code=400)

        try:
            message_data = await request.json()
        except json.JSONDecodeError:
            return Response("Invalid JSON", status_code=400)

        # Validate JSON-RPC message structure
        if not self._is_valid_jsonrpc_message(message_data):
            return Response("Invalid JSON-RPC message", status_code=400)

        # Validate session requirements
        if not self._has_valid_session(request, message_data):
            return self._build_session_error_response(request, message_data)

        client_id, session_id = await self._get_or_create_client(request, message_data)

        response_headers = self._build_response_headers(request, session_id)

        client_message = ClientMessage(
            client_id=client_id,
            payload=message_data,
            timestamp=time.time(),
        )
        await self._message_queue.put(client_message)

        if self._is_mcp_request(message_data):
            request_id = message_data.get("id")
            if request_id is None:
                return Response(
                    "Request missing id field",
                    status_code=400,
                    headers=response_headers,
                )

            return await self._create_request_stream(
                client_id, request_id, response_headers
            )
        else:
            return Response(status_code=202, headers=response_headers)

    async def _handle_get_request(self, request: Request) -> Response:
        """Handle HTTP GET request for SSE streams."""
        # TODO: Phase 3 - Server-initiated message streams
        return Response("Server streams not implemented", status_code=501)

    async def _handle_delete_request(self, request: Request) -> Response:
        """Handle session termination."""
        session_id = request.headers.get("Mcp-Session-Id")
        if not session_id:
            return Response("Missing session ID", status_code=400)

        client_id = self._session_manager.terminate_session(session_id)
        if client_id is None:
            return Response("Session not found", status_code=404)

        return Response(status_code=200)

    def _has_valid_protocol_headers(self, request: Request) -> bool:
        """Validate required MCP protocol headers (Protocol-Version, Accept, Origin)."""
        protocol_version = request.headers.get("MCP-Protocol-Version")
        if protocol_version != PROTOCOL_VERSION:
            logger.warning("Invalid MCP-Protocol-Version header")
            return False

        accept = request.headers.get("Accept")
        if "text/event-stream" not in accept and "application/json" not in accept:
            logger.warning("Invalid Accept header")
            return False

        # TODO: Implement proper Origin validation to prevent DNS rebinding attacks
        # For now, we accept all origins (development mode)
        origin = request.headers.get("Origin")
        if not self._is_valid_origin(origin):
            logger.warning(f"Invalid Origin header: {origin}")
            return False

        return True

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

    def _has_valid_session(self, request: Request, message_data: dict) -> bool:
        """Check if the request meets session ID requirements.

        Returns True if session requirements are met, False otherwise.
        """
        session_id = request.headers.get("Mcp-Session-Id")
        is_initialize = (
            self._is_mcp_request(message_data)
            and message_data.get("method") == "initialize"
        )

        if is_initialize:
            # Initialize requests should NOT have a session ID
            return session_id is None
        else:
            # All other messages MUST have a valid session ID
            return session_id is not None and self._session_manager.session_exists(
                session_id
            )

    def _build_session_error_response(
        self, request: Request, message_data: dict
    ) -> Response:
        """Build appropriate error response for session validation failures."""
        session_id = request.headers.get("Mcp-Session-Id")
        is_initialize = (
            self._is_mcp_request(message_data)
            and message_data.get("method") == "initialize"
        )

        if is_initialize and session_id:
            return Response(
                "Initialize request must not include session ID", status_code=400
            )
        elif not is_initialize and not session_id:
            return Response("Missing required Mcp-Session-Id header", status_code=400)
        elif not is_initialize and not self._session_manager.session_exists(session_id):
            return Response("Invalid or expired session", status_code=404)
        else:
            # Shouldn't reach here, but safe fallback
            return Response("Session validation failed", status_code=400)

    async def _get_or_create_client(
        self, request: Request, message_data: dict
    ) -> tuple[str, str]:
        """Get existing client or create new session for initialize requests.

        Returns:
            Tuple of (client_id, session_id)
        """
        session_id = request.headers.get("Mcp-Session-Id")
        is_initialize = (
            self._is_mcp_request(message_data)
            and message_data.get("method") == "initialize"
        )

        if is_initialize:
            # Create new session for initialize request
            session_id, client_id = self._session_manager.create_session()
            return client_id, session_id
        else:
            # Use existing session (we've already validated it exists)
            client_id = self._session_manager.get_client_id(session_id)
            return client_id, session_id

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

    def _is_mcp_request(self, message_data: dict[str, Any]) -> bool:
        """Check if message is an MCP request (has method field and id)."""
        return self._message_parser.is_valid_request(message_data)

    def _is_valid_jsonrpc_message(self, message_data: dict) -> bool:
        """Validate JSON-RPC message structure.

        Returns True if valid, False otherwise.
        """
        is_request = self._message_parser.is_valid_request(message_data)
        is_response = self._message_parser.is_valid_response(message_data)
        is_notification = self._message_parser.is_valid_notification(message_data)

        if not (is_request or is_response or is_notification):
            return False
        return True

    # ServerTransport interface implementation

    async def send(
        self,
        client_id: str,
        message: dict[str, Any],
        transport_context: TransportContext | None = None,
    ) -> None:
        """Send message to specific client."""
        originating_request_id = (
            transport_context.originating_request_id if transport_context else None
        )

        # Try to send to existing stream
        if await self._stream_manager.send_to_existing_stream(
            client_id, message, originating_request_id
        ):
            return

        # Fallback: server-initiated message (Phase 3)
        await self._handle_server_initiated_message(client_id, message)

    async def _create_request_stream(
        self, client_id: str, request_id: str | int, headers: dict[str, str]
    ) -> StreamingResponse:
        """Create SSE stream for a request.

        The stream will:
        1. Send any server-initiated messages (requests/notifications)
        2. Send the final response to the original request
        3. Auto-close after sending the response
        """
        stream = await self._stream_manager.create_request_stream(
            client_id, str(request_id)
        )

        return StreamingResponse(
            stream.event_generator(), media_type="text/event-stream", headers=headers
        )

    async def _handle_server_initiated_message(
        self, client_id: str, message: dict[str, Any]
    ) -> None:
        """Handle server-initiated messages when no request stream exists.

        TODO: Phase 3 - Route to server streams or buffer for later delivery.
        For now, log and drop the message.
        """
        logger.warning(
            f"Dropping server-initiated message for client {client_id}: "
            f"no active streams and server streams not yet implemented"
        )

    def client_messages(self) -> AsyncIterator[ClientMessage]:
        """Stream of messages from all clients."""
        return self._message_queue_iterator()

    async def _message_queue_iterator(self) -> AsyncIterator[ClientMessage]:
        """Async iterator that yields messages from the queue."""
        while True:
            try:
                message = await self._message_queue.get()
                yield message
            except Exception as e:
                logger.error(f"Error reading from message queue: {e}")
                break

    async def disconnect_client(self, client_id: str) -> None:
        """Disconnect specific client."""
        session_id = self._session_manager.get_session_id(client_id)
        if session_id:
            self._session_manager.terminate_session(session_id)

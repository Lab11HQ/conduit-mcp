import asyncio
from collections.abc import AsyncIterator
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from conduit.transport.base import Transport, TransportMessage
from conduit.transport.http.server.connection_manager import ConnectionManager
from conduit.transport.http.server.message_sender import ServerMessageSender
from conduit.transport.http.server.stream_manager import ServerStreamManager


class HTTPServerTransport(Transport):
    """HTTP server transport implementing the Transport interface.

    Coordinates multiple client connections through a unified transport interface.
    Handles HTTP endpoints, session management, and message routing.
    """

    def __init__(self, host: str = "localhost", port: int = 8000):
        self._host = host
        self._port = port

        # Component coordination
        self._connection_manager = ConnectionManager()
        self._message_sender = ServerMessageSender(self._connection_manager)
        self._stream_manager = ServerStreamManager(self._connection_manager)

        # Unified message queue (from ALL clients)
        self._message_queue: asyncio.Queue[TransportMessage] = asyncio.Queue()

        # Starlette app
        self._app = self._create_app()
        self._server_task: asyncio.Task | None = None
        self._closed = False

    def _create_app(self) -> Starlette:
        """Create the Starlette application with MCP endpoints."""
        routes = [
            Route("/mcp", self._handle_post, methods=["POST"]),
            Route("/mcp", self._handle_get, methods=["GET"]),
            Route("/mcp", self._handle_delete, methods=["DELETE"]),
        ]

        return Starlette(routes=routes)

    async def _handle_post(self, request: Request) -> Response:
        """Handle POST requests - client sending messages to server."""
        # Extract session ID
        session_id = request.headers.get("Mcp-Session-Id")

        # Parse JSON-RPC message
        try:
            message_data = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        # Handle initialization specially (no session ID yet)
        if self._is_initialize_request(message_data):
            return await self._handle_initialize(message_data)

        # Validate session for all other requests
        if not self._connection_manager.validate_session(session_id):
            return JSONResponse({"error": "Invalid session"}, status_code=404)

        # Route message based on type
        if self._is_notification(message_data):
            await self._handle_notification(session_id, message_data)
            return Response(status_code=202)  # Accepted

        elif self._is_response(message_data):
            await self._handle_response(session_id, message_data)
            return Response(status_code=202)  # Accepted

        elif self._is_request(message_data):
            return await self._handle_request(session_id, message_data)

        else:
            return JSONResponse({"error": "Invalid message type"}, status_code=400)

    async def _handle_get(self, request: Request) -> StreamingResponse:
        """Handle GET requests - client opening listening stream."""
        session_id = request.headers.get("Mcp-Session-Id")
        last_event_id = request.headers.get("Last-Event-ID")

        # Validate session
        if not self._connection_manager.validate_session(session_id):
            return JSONResponse({"error": "Invalid session"}, status_code=404)

        # Create listening stream
        stream_iterator = await self._stream_manager.create_listening_stream(
            client_id=session_id, last_event_id=last_event_id
        )

        return StreamingResponse(
            stream_iterator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    async def _handle_delete(self, request: Request) -> Response:
        """Handle DELETE requests - client terminating session."""
        session_id = request.headers.get("Mcp-Session-Id")

        if self._connection_manager.terminate_session(session_id):
            # Clean up resources
            await self._stream_manager.cleanup_client(session_id)
            return Response(status_code=200)
        else:
            return Response(status_code=405)  # Method Not Allowed

    async def _handle_initialize(self, message_data: dict[str, Any]) -> JSONResponse:
        """Handle InitializeRequest - create new session."""
        # Create new session
        session_id = self._connection_manager.create_session()

        # TODO: Process initialize request properly
        # - Validate client capabilities
        # - Set server capabilities
        # - Create proper InitializeResult

        initialize_result = {
            "jsonrpc": "2.0",
            "id": message_data.get("id"),
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "conduit-mcp-server", "version": "0.1.0"},
            },
        }

        return JSONResponse(initialize_result, headers={"Mcp-Session-Id": session_id})

    # Transport interface implementation
    async def send(self, message: dict[str, Any]) -> None:
        """Send message to a client.

        NOTE: This is tricky for server - which client?
        We might need to modify this interface or handle it differently.
        """
        # TODO: How do we determine target client?
        # Option 1: Message contains client context
        # Option 2: Different interface for server
        # Option 3: Broadcast to all clients

        raise NotImplementedError("Server send() needs client targeting")

    def messages(self) -> AsyncIterator[TransportMessage]:
        """Unified stream of messages from ALL clients."""
        return self._message_queue_iterator()

    async def _message_queue_iterator(self) -> AsyncIterator[TransportMessage]:
        """Async iterator over messages from all clients."""
        while not self._closed:
            try:
                message = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield message
            except asyncio.TimeoutError:
                continue

    @property
    def is_open(self) -> bool:
        """True if the transport is open and accepting connections."""
        return not self._closed

    async def close(self) -> None:
        """Close the transport and all client connections."""
        self._closed = True

        # Stop HTTP server
        if self._server_task:
            self._server_task.cancel()

        # Clean up components
        await self._stream_manager.close()
        await self._message_sender.close()

    # Helper methods
    def _is_initialize_request(self, message: dict[str, Any]) -> bool:
        return message.get("method") == "initialize"

    def _is_notification(self, message: dict[str, Any]) -> bool:
        return "method" in message and "id" not in message

    def _is_response(self, message: dict[str, Any]) -> bool:
        return "result" in message or "error" in message

    def _is_request(self, message: dict[str, Any]) -> bool:
        return "method" in message and "id" in message

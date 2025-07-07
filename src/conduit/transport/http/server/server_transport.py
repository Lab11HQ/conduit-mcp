import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from conduit.transport.http.server.connection_manager import ConnectionManager
from conduit.transport.http.server.message_sender import MessageSender
from conduit.transport.http.server.stream_manager import StreamManager
from conduit.transport.server import ClientMessage, ServerTransport


class HTTPTransport(ServerTransport):
    """HTTP server transport implementing the ServerTransport protocol.

    Handles multiple client connections with explicit client targeting.
    Provides clean 1:many communication interface.
    """

    def __init__(self, host: str = "localhost", port: int = 8000):
        self._host = host
        self._port = port

        # Component coordination
        self._connection_manager = ConnectionManager()
        self._message_sender = MessageSender(self._connection_manager)
        self._stream_manager = StreamManager(self._connection_manager)

        # Client message queue (from ALL clients with context)
        self._message_queue: asyncio.Queue[ClientMessage] = asyncio.Queue()

        # Starlette app
        self._app = self._create_app()
        self._server_task: asyncio.Task | None = None
        self._closed = False

    # ServerTransport protocol implementation
    async def send_to_client(self, client_id: str, message: dict[str, Any]) -> None:
        """Send message to specific client."""
        await self._message_sender.send_to_client(client_id, message)

    async def broadcast(
        self, message: dict[str, Any], exclude: set[str] | None = None
    ) -> None:
        """Send message to all connected clients."""
        active_clients = self._connection_manager.get_active_sessions()

        for client_id in active_clients:
            if exclude and client_id in exclude:
                continue
            try:
                await self._message_sender.send_to_client(client_id, message)
            except ValueError:
                # Client disconnected during broadcast - skip
                continue

    def client_messages(self) -> AsyncIterator[ClientMessage]:
        """Stream of messages from all clients with client context."""
        return self._client_message_iterator()

    def active_clients(self) -> set[str]:
        """Get currently connected client IDs."""
        return self._connection_manager.get_active_sessions()

    async def disconnect_client(self, client_id: str) -> None:
        """Disconnect specific client."""
        if self._connection_manager.terminate_session(client_id):
            await self._stream_manager.cleanup_client(client_id)

    @property
    def is_open(self) -> bool:
        """True if server is open and accepting connections."""
        return not self._closed

    async def close(self) -> None:
        """Close server and disconnect all clients."""
        self._closed = True

        # Stop HTTP server
        if self._server_task:
            self._server_task.cancel()

        # Clean up components
        await self._stream_manager.close()  # NOT IMPLEMENTED
        await self._message_sender.close()  # NOT IMPLEMENTED

    # HTTP endpoint handlers (unchanged)
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
            response = await self._handle_request(session_id, message_data)
            return response

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

    # Message handling methods (NEW - these were missing!)
    async def _handle_notification(
        self, client_id: str, message_data: dict[str, Any]
    ) -> None:
        """Handle notification from client - add to message queue."""
        client_message = ClientMessage(
            client_id=client_id,
            payload=message_data,
            timestamp=time.time(),
            metadata={"type": "notification"},
        )
        await self._message_queue.put(client_message)

    async def _handle_response(
        self, client_id: str, message_data: dict[str, Any]
    ) -> None:
        """Handle response from client - add to message queue."""
        client_message = ClientMessage(
            client_id=client_id,
            payload=message_data,
            timestamp=time.time(),
            metadata={"type": "response"},
        )
        await self._message_queue.put(client_message)

    async def _handle_request(
        self, client_id: str, message_data: dict[str, Any]
    ) -> JSONResponse:
        """Handle request from client - add to message queue and return response."""
        client_message = ClientMessage(
            client_id=client_id,
            payload=message_data,
            timestamp=time.time(),
            metadata={"type": "request"},
        )
        await self._message_queue.put(client_message)

        # For requests, we need to return a response immediately
        # The session layer will handle the actual request processing
        return JSONResponse(
            {"jsonrpc": "2.0", "id": message_data.get("id"), "result": {}}
        )

    # Message queue iterator
    async def _client_message_iterator(self) -> AsyncIterator[ClientMessage]:
        """Async iterator over client messages."""
        while not self._closed:
            try:
                message = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield message
            except asyncio.TimeoutError:
                continue

    # Helper methods
    def _is_initialize_request(self, message: dict[str, Any]) -> bool:
        return message.get("method") == "initialize"

    def _is_notification(self, message: dict[str, Any]) -> bool:
        return "method" in message and "id" not in message

    def _is_response(self, message: dict[str, Any]) -> bool:
        return "result" in message or "error" in message

    def _is_request(self, message: dict[str, Any]) -> bool:
        return "method" in message and "id" in message

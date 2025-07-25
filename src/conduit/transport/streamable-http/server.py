"""Streamable HTTP server transport implementation."""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from conduit.transport.server import ClientMessage, ServerTransport, TransportContext

logger = logging.getLogger(__name__)


class StreamableHttpServerTransport(ServerTransport):
    """HTTP server transport supporting multiple client connections.

    ARCHITECTURAL INSIGHT: "Always Stream" Strategy
    ===============================================

    The MCP spec allows servers to respond to requests with either:
    1. Immediate JSON response, or
    2. SSE stream that eventually contains the response

    We choose "always stream" for requests because:
    - Eliminates decision complexity (no need to choose response type)
    - Consistent client experience (always expect text/event-stream)
    - Future-proofs for server-initiated messages
    - Minimal performance overhead with modern HTTP/2
    - Clean stream lifecycle: create → send messages → send response → close

    This moves complexity from "how do we decide?" to "how do we manage
    stream lifecycle?" which is more contained and architecturally sound.
    """

    def __init__(
        self, endpoint_path: str = "/mcp", host: str = "127.0.0.1", port: int = 8000
    ) -> None:
        """Initialize HTTP server transport."""
        self.endpoint_path = endpoint_path
        self.host = host
        self.port = port

        # Client and session management
        self._sessions: dict[str, str] = {}  # session_id -> client_id
        self._client_sessions: dict[str, str] = {}  # client_id -> session_id
        self._message_queue: asyncio.Queue[ClientMessage] = asyncio.Queue()

        # Stream management (Phase 2)
        self._active_streams: dict[str, "RequestStream"] = {}  # stream_id -> stream
        self._client_streams: dict[str, set[str]] = {}  # client_id -> set of stream_ids

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
        """Handle MCP endpoint requests."""
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
        """Handle HTTP POST request with JSON-RPC message.

        ALWAYS STREAM STRATEGY:
        - Notifications/Responses → 202 Accepted (no stream needed)
        - Requests → SSE stream (always, regardless of complexity)
        """
        # Validate headers
        if not self._validate_headers(request):
            return Response("Bad request", status_code=400)

        # Get or create client ID from session
        client_id = await self._get_or_create_client_id(request)

        # Parse JSON-RPC message
        try:
            message_data = await request.json()
        except json.JSONDecodeError:
            return Response("Invalid JSON", status_code=400)

        # Handle session management for InitializeRequest
        response_headers = self._build_response_headers(
            request, message_data, client_id
        )

        # Put message in queue for session layer
        client_message = ClientMessage(
            client_id=client_id,
            payload=message_data,
            timestamp=time.time(),
        )
        await self._message_queue.put(client_message)

        # Route based on message type
        request_id = message_data.get("id")
        if request_id:
            # ALWAYS create SSE stream for requests
            return await self._create_request_stream(
                client_id, request_id, response_headers
            )
        else:
            # Notifications and responses get 202 Accepted
            return Response(status_code=202, headers=response_headers)

    async def _handle_get_request(self, request: Request) -> Response:
        """Handle HTTP GET request for SSE streams."""
        # Phase 1: Not implemented yet
        return Response("Method not allowed", status_code=405)

    async def _handle_delete_request(self, request: Request) -> Response:
        """Handle session termination."""
        session_id = request.headers.get("Mcp-Session-Id")
        if not session_id or session_id not in self._sessions:
            return Response("Session not found", status_code=404)

        client_id = self._sessions[session_id]
        del self._sessions[session_id]
        del self._client_sessions[client_id]

        logger.debug(f"Terminated session {session_id} for client {client_id}")
        return Response(status_code=200)

    def _validate_headers(self, request: Request) -> bool:
        """Validate required MCP headers."""
        # Check protocol version
        protocol_version = request.headers.get("MCP-Protocol-Version")
        if not protocol_version:
            logger.warning("Missing MCP-Protocol-Version header")
            return False

        # Check Accept header has both application/json and text/event-stream

        # Validate Origin header—this is a security measure to prevent DNS rebinding
        # attacks
        return True

    async def _get_or_create_client_id(self, request: Request) -> str:
        """Get client ID from session or create new one."""
        session_id = request.headers.get("Mcp-Session-Id")

        if session_id and session_id in self._sessions:
            return self._sessions[session_id]

        # Create new client ID (for requests without session)
        client_id = str(uuid.uuid4())
        return client_id

    def _generate_session_id(self) -> str:
        """Generate cryptographically secure session ID."""
        import secrets

        return secrets.token_urlsafe(32)

    def _build_response_headers(
        self, request: Request, message_data: dict, client_id: str
    ) -> dict[str, str]:
        """Build standard response headers for all responses."""
        headers = {
            "Access-Control-Allow-Origin": request.headers.get(
                "Origin", "*"
            ),  # TODO: Validate origin
            "Cache-Control": "no-cache",
        }

        # Handle session creation for InitializeRequest
        if message_data.get("method") == "initialize":
            session_id = self._generate_session_id()
            self._sessions[session_id] = client_id
            self._client_sessions[client_id] = session_id
            headers["Mcp-Session-Id"] = session_id
            logger.debug(f"Created session {session_id} for client {client_id}")

        # TODO: Mcp-Protocol-Version and Mcp-Session-Id on all responses
        return headers

    async def _create_request_stream(
        self, client_id: str, request_id: str, headers: dict[str, str]
    ) -> StreamingResponse:
        """Create SSE stream for a request.

        The stream will:
        1. Send any server-initiated messages (requests/notifications)
        2. Send the final response to the original request
        3. Auto-close after sending the response
        """
        stream_id = f"{client_id}:{request_id}"

        # Create stream context
        stream = RequestStream(
            stream_id=stream_id,
            client_id=client_id,
            request_id=request_id,
        )

        # Register stream
        self._active_streams[stream_id] = stream
        if client_id not in self._client_streams:
            self._client_streams[client_id] = set()
        self._client_streams[client_id].add(stream_id)

        logger.debug(f"Created SSE stream {stream_id} for client {client_id}")

        # Return SSE streaming response
        headers.update(
            {
                "Content-Type": "text/event-stream",
                "Connection": "keep-alive",
            }
        )

        return StreamingResponse(
            stream.event_generator(), media_type="text/event-stream", headers=headers
        )

    async def send(
        self,
        client_id: str,
        message: dict[str, Any],
        transport_context: TransportContext | None = None,
    ) -> None:
        if transport_context and (
            originating_request_id := transport_context.originating_request_id
        ):
            # Route to the stream for the originating request
            stream_id = f"{client_id}:{originating_request_id}"
            if stream_id in self._active_streams:
                await self._active_streams[stream_id].send_message(message)
                # Auto-close stream after sending response
                if "result" in message or "error" in message:
                    await self._close_stream(stream_id)
                return

        # Fallback: server-initiated message (Phase 3)
        await self._route_to_server_stream(client_id, message)

    async def _close_stream(self, stream_id: str) -> None:
        """Close and cleanup a stream."""
        if stream_id not in self._active_streams:
            return

        stream = self._active_streams[stream_id]
        await stream.close()

        # Cleanup tracking
        del self._active_streams[stream_id]
        if stream.client_id in self._client_streams:
            self._client_streams[stream.client_id].discard(stream_id)
            if not self._client_streams[stream.client_id]:
                del self._client_streams[stream.client_id]

        logger.debug(f"Closed stream {stream_id}")

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
        # Clean up session if exists
        if client_id in self._client_sessions:
            session_id = self._client_sessions[client_id]
            del self._sessions[session_id]
            del self._client_sessions[client_id]
            logger.debug(f"Disconnected client {client_id} (session {session_id})")


class RequestStream:
    """Manages a single SSE stream for a request.

    Handles the stream lifecycle:
    1. Created when request arrives
    2. Sends server messages and final response
    3. Auto-closes after response sent
    """

    def __init__(self, stream_id: str, client_id: str, request_id: str):
        self.stream_id = stream_id
        self.client_id = client_id
        self.request_id = request_id
        self.message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.closed = False

    async def send_message(self, message: dict[str, Any]) -> None:
        """Send a message on this stream."""
        if not self.closed:
            await self.message_queue.put(message)

    async def close(self) -> None:
        """Close the stream."""
        self.closed = True
        # Send sentinel to stop the generator
        await self.message_queue.put({"__close__": True})

    async def event_generator(self):
        """Generate SSE events for this stream."""
        try:
            while not self.closed:
                message = await self.message_queue.get()

                # Check for close sentinel
                if message.get("__close__"):
                    break

                # Format as SSE event
                event_data = json.dumps(message, separators=(",", ":"))
                yield f"data: {event_data}\n\n"

        except Exception as e:
            logger.error(f"Error in stream {self.stream_id}: {e}")
        finally:
            logger.debug(f"Stream {self.stream_id} generator closed")

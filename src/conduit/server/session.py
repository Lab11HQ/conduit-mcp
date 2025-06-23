import asyncio
import uuid
from typing import Any, Callable

from conduit.protocol.base import METHOD_NOT_FOUND, Error, Notification, Request, Result
from conduit.protocol.common import CancelledNotification, PingRequest
from conduit.protocol.initialization import (
    Implementation,
    InitializedNotification,
    ServerCapabilities,
)
from conduit.protocol.jsonrpc import JSONRPCRequest
from conduit.protocol.tools import CallToolRequest, Tool
from conduit.shared.session import BaseSession
from conduit.transport.base import Transport

NOTIFICATION_CLASSES: dict[str, type[Notification]] = {
    "notifications/initialized": InitializedNotification,
}

REQUEST_CLASSES: dict[str, type[Request]] = {
    "ping": PingRequest,
}


class ServerSession(BaseSession):
    def __init__(
        self,
        transport: Transport,
        server_info: Implementation,
        capabilities: ServerCapabilities,
    ):
        super().__init__(transport)
        self.server_info = server_info
        self.capabilities = capabilities
        self._received_initialized_notification = False

        # Handler registries
        self._tool_handlers = {}

        # Tool definitions - for list operations
        self._registered_tools: dict[str, Tool] = {}

    @property
    def initialized(self) -> bool:
        return self._received_initialized_notification

    async def send_request(
        self,
        request: Request,
        timeout: float = 30.0,
    ) -> Result | Error | None:
        """Send a request to the client and wait for its response.

        Handles the complete request lifecycle—generates IDs, manages
        timeouts, and cleans up automatically. Returns None for fire-and-forget
        requests.

        Most requests require an initialized session. PingRequests work anytime
        since they test basic connectivity.

        Args:
            request: The MCP request to send
            timeout: How long to wait for a response (seconds)

        Returns:
            Client's response, or None for requests that don't expect replies.

        Raises:
            RuntimeError: Session not initialized (client hasn't sent initialized
                notification)
            TimeoutError: Client didn't respond in time
        """
        await self.start_message_loop()

        if not self.initialized and not isinstance(request, PingRequest):
            raise RuntimeError(
                "Session must be initialized before sending non-ping requests. "
                "Client must send initialized notification first."
            )

        # Generate request ID and create JSON-RPC wrapper
        request_id = str(uuid.uuid4())
        jsonrpc_request = JSONRPCRequest.from_request(request, request_id)

        # If the request doesn't have a result type, we don't need to wait for a
        # response.
        if request.expected_result_type() is None:
            await self.transport.send(jsonrpc_request.to_wire())
            return

        future: asyncio.Future[Result | Error] = asyncio.Future()
        self._pending_requests[request_id] = (request, future)

        try:
            await self.transport.send(jsonrpc_request.to_wire())
            result = await asyncio.wait_for(future, timeout)
            return result
        except asyncio.TimeoutError:
            try:
                cancelled_notification = CancelledNotification(
                    request_id=request_id,
                    reason="Request timed out",
                )
                await self.send_notification(cancelled_notification)
            except Exception as e:
                print(f"Error sending cancellation notification: {e}")
            raise TimeoutError(f"Request {request_id} timed out after {timeout}s")
        finally:
            self._pending_requests.pop(request_id, None)

    async def _handle_notification(self, payload: dict[str, Any]) -> None:
        """Handle notifications, tracking initialization."""
        notification = self._parse_notification(payload)

        if isinstance(notification, InitializedNotification):
            self._received_initialized_notification = True

        await self.notifications.put(notification)

    def _get_supported_notifications(self) -> dict[str, type[Notification]]:
        return NOTIFICATION_CLASSES

    def _get_supported_requests(self) -> dict[str, type[Request]]:
        return REQUEST_CLASSES

    async def _handle_peer_request(self, request: Request) -> Result | Error:
        # TODO: Implement server request handlers
        return Error(
            code=METHOD_NOT_FOUND,
            message=f"Unknown request: {request.method}",
        )

    def register_tool(
        self, name: str, handler: Callable[[Tool], Result | Error], tool_def: Tool
    ) -> None:
        self._tool_handlers[name] = handler
        self._registered_tools[name] = tool_def

    def _handle_call_tool(self, request: CallToolRequest) -> Result | Error:
        # Capability check and handler execution
        ...

from typing import Any, Callable

from conduit.protocol.base import METHOD_NOT_FOUND, Error, Notification, Request, Result
from conduit.protocol.common import PingRequest
from conduit.protocol.initialization import (
    Implementation,
    InitializedNotification,
    ServerCapabilities,
)
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

    async def _ensure_can_send_request(self, request: Request) -> None:
        if not self.initialized and not isinstance(request, PingRequest):
            raise RuntimeError(
                "Session must be initialized before sending non-ping requests. "
                "Client must send initialized notification first."
            )

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

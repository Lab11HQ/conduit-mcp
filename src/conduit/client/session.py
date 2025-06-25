"""Low-level MCP client session implementation.

This module contains the internal protocol engine that handles MCP communication.
Most users should use the higher-level MCPClient class instead—this is for when you
need direct control over the protocol lifecycle.

The ClientSession manages JSON-RPC message routing, maintains connection state,
and handles the MCP initialization handshake. It's designed to be wrapped by
more user-friendly interfaces.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from conduit.protocol.base import (
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    Error,
    Request,
    Result,
)
from conduit.protocol.common import (
    EmptyResult,
    PingRequest,
)
from conduit.protocol.elicitation import ElicitRequest
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
)
from conduit.protocol.jsonrpc import JSONRPCRequest
from conduit.protocol.roots import ListRootsRequest, ListRootsResult, Root
from conduit.protocol.sampling import CreateMessageRequest
from conduit.shared.exceptions import UnknownRequestError
from conduit.shared.session import BaseSession
from conduit.transport.base import Transport

T = TypeVar("T", bound=Request)
RequestHandler = Callable[[T], Awaitable[Result | Error]]
RequestRegistryEntry = tuple[type[T], RequestHandler[T]]


class ClientSession(BaseSession):
    """Manages the low-level MCP client protocol and connection lifecycle.

    Handles JSON-RPC message routing, request/response correlation, and
    server communication over a transport. This is the internal engine—
    most users should use the higher-level MCPClient class instead.

    Key responsibilities:
    - MCP initialization handshake
    - Bidirectional message processing (requests, responses, notifications)

    Args:
        transport: Communication channel to the MCP server.
        client_info: Client identification and version info.
        capabilities: What MCP features this client supports.
        roots: Filesystem roots to expose (if roots capability enabled).

    Raises:
        ValueError: Sampling capability enabled without handler.
    """

    def __init__(
        self,
        transport: Transport,
        client_info: Implementation,
        capabilities: ClientCapabilities,
        roots: list[Root] | None = None,
    ):
        super().__init__(transport)
        self.client_info = client_info
        self.capabilities = capabilities
        self.roots = roots or []  # TODO: Hook this up to notifcations.
        self._custom_handlers = {}

        self._initializing: asyncio.Future[InitializeResult] | None = None
        self._initialize_result: InitializeResult | None = None

    @property
    def initialized(self) -> bool:
        return self._initialize_result is not None

    async def initialize(self, timeout: float = 30.0) -> InitializeResult:
        """Initialize your MCP session with the server.

        Call this once after creating your session—it handles the handshake and
        starts the message loop. Safe to call multiple times.

        Args:
            timeout: How long to wait for the server (seconds).

        Returns:
            Server capabilities and connection details.

        Raises:
            TimeoutError: Server didn't respond in time.
            ValueError: Server uses incompatible protocol version.
            ConnectionError: Connection failed during handshake.
        """
        await self.start_message_loop()

        if self._initialize_result is not None:
            return self._initialize_result

        if self._initializing:
            return await self._initializing

        self._initializing = asyncio.create_task(self._do_initialize(timeout))
        try:
            result = await self._initializing
            return result
        finally:
            self._initializing = None

    async def _ensure_can_send_request(self, request: Request) -> None:
        if not self.initialized and not isinstance(request, PingRequest):
            raise RuntimeError(
                "Session must be initialized before sending non-ping requests. "
                "Call initialize() first."
            )

    async def _do_initialize(self, timeout: float = 30.0) -> InitializeResult:
        """Execute the MCP initialization handshake.

        Performs the three-step protocol: send request, validate response,
        send completion notification. Stops the session on any failure to
        prevent partial initialization.

        Args:
            timeout: Maximum seconds to wait for server response.

        Returns:
            Validated server initialization result.

        Raises:
            TimeoutError: Server didn't respond in time.
            ValueError: Protocol version mismatch or server error.
            ConnectionError: Transport failure.
        """
        await self.start_message_loop()
        init_request = InitializeRequest(
            client_info=self.client_info,
            capabilities=self.capabilities,
        )
        request_id = str(uuid.uuid4())
        jsonrpc_request = JSONRPCRequest.from_request(init_request, request_id)

        # Set up response waiting.
        future: asyncio.Future[Result | Error] = asyncio.Future()
        self._pending_requests[request_id] = (init_request, future)

        try:
            await self.transport.send(jsonrpc_request.to_wire())
            response = await asyncio.wait_for(future, timeout)
            if isinstance(response, Error):
                await self.close()
                raise ValueError(f"Initialization failed: {response}")

            init_result = cast(InitializeResult, response)
            if (
                init_result.protocol_version != PROTOCOL_VERSION
            ):  # TODO: Handle this better. SEND A INVALID_PARAMS ERROR.
                await self.close()
                raise ValueError(
                    f"Protocol version mismatch: client version {PROTOCOL_VERSION} !="
                    f" server version {init_result.protocol_version}"
                )

            initialized_notification = InitializedNotification()
            await self.send_notification(initialized_notification)

            self._initialize_result = init_result
            return init_result
        except asyncio.TimeoutError:
            await self.close()
            raise TimeoutError(f"Initialization timed out after {timeout}s")
        except Exception:
            await self.close()
            raise
        finally:
            self._pending_requests.pop(request_id, None)

    async def _handle_session_request(self, payload: dict[str, Any]) -> Result | Error:
        """Handle client-specific requests."""
        method = payload["method"]

        registry = self._get_request_registry()
        if method not in registry:
            raise UnknownRequestError(method)

        request_class, handler = registry[method]
        request = request_class.from_protocol(payload)
        return await handler(request)

    async def _handle_ping(self, request: PingRequest) -> Result | Error:
        """Handle server request for ping.

        Returns:
            PingResult with pong.
        """
        return EmptyResult()

    async def _handle_list_roots(self, request: ListRootsRequest) -> Result | Error:
        """Handle server request for filesystem roots.

        Returns available roots if client advertised roots capability,
        otherwise METHOD_NOT_FOUND error.

        Args:
            request: Parsed roots/list request.

        Returns:
            ListRootsResult with roots, or Error if capability missing.
        """
        if self.capabilities.roots is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support roots capability",
            )
        return ListRootsResult(roots=self.roots)

    def _get_request_registry(self) -> dict[str, RequestRegistryEntry]:
        return {
            "ping": (PingRequest, self._handle_ping),
            "roots/list": (ListRootsRequest, self._handle_list_roots),
            "sampling/createMessage": (
                CreateMessageRequest,
                self._handle_sampling,
            ),
            "elicitation/create": (ElicitRequest, self._handle_elicitation),
        }

    async def _handle_sampling(self, request: CreateMessageRequest) -> Result | Error:
        if not self.capabilities.sampling:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support sampling capability",
            )

        if "sampling/createMessage" not in self._custom_handlers:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client not configured with a create message handler",
            )

        return await self._custom_handlers["sampling/createMessage"](request)

    async def _handle_elicitation(self, request: ElicitRequest) -> Result | Error:
        """Handle server request for elicitation."""
        if not self.capabilities.elicitation:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support elicitation capability",
            )

        if "elicitation/create" not in self._custom_handlers:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client not configured with a elicitation handler",
            )

        return await self._custom_handlers["elicitation/create"](request)

    # Handler registration methods
    def set_sampling_handler(self, handler: RequestHandler[CreateMessageRequest]):
        """Register a handler for sampling/createMessage requests."""
        self._custom_handlers["sampling/createMessage"] = handler
        return self  # For method chaining

    def set_elicitation_handler(self, handler: RequestHandler[ElicitRequest]):
        """Register a handler for elicitation/create requests."""
        self._custom_handlers["elicitation/create"] = handler
        return self  # For method chaining

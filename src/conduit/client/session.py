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
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from conduit.client.managers.callbacks import CallbackManager
from conduit.client.managers.elicitation import (
    ElicitationManager,
    ElicitationNotConfiguredError,
)
from conduit.client.managers.roots import RootsManager
from conduit.client.managers.sampling import SamplingManager, SamplingNotConfiguredError
from conduit.protocol.base import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    Error,
    Notification,
    Request,
    Result,
)
from conduit.protocol.common import (
    CancelledNotification,
    EmptyResult,
    PingRequest,
    ProgressNotification,
)
from conduit.protocol.elicitation import ElicitRequest, ElicitResult
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
    ServerCapabilities,
)
from conduit.protocol.jsonrpc import JSONRPCError, JSONRPCRequest
from conduit.protocol.logging import LoggingMessageNotification
from conduit.protocol.prompts import (
    ListPromptsRequest,
    ListPromptsResult,
    Prompt,
    PromptListChangedNotification,
)
from conduit.protocol.resources import (
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    Resource,
    ResourceListChangedNotification,
    ResourceTemplate,
    ResourceUpdatedNotification,
)
from conduit.protocol.roots import ListRootsRequest, ListRootsResult
from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult
from conduit.protocol.tools import (
    ListToolsRequest,
    ListToolsResult,
    Tool,
    ToolListChangedNotification,
)
from conduit.protocol.unions import NOTIFICATION_REGISTRY
from conduit.shared.exceptions import UnknownNotificationError, UnknownRequestError
from conduit.shared.session import BaseSession
from conduit.transport.base import Transport

TRequest = TypeVar("TRequest", bound=Request)
TResult = TypeVar("TResult", bound=Result)
RequestHandler = Callable[[TRequest], Awaitable[TResult | Error]]
RequestRegistryEntry = tuple[type[TRequest], RequestHandler[TRequest, TResult]]
TNotification = TypeVar("TNotification", bound=Notification)
NotificationHandler = Callable[[TNotification], Awaitable[None]]


class InvalidProtocolVersionError(Exception):
    pass


@dataclass
class ClientConfig:
    client_info: Implementation
    capabilities: ClientCapabilities
    protocol_version: str = PROTOCOL_VERSION


@dataclass
class ServerState:
    capabilities: ServerCapabilities | None = None
    instructions: str | None = None
    info: Implementation | None = None

    tools: list[Tool] | None = None
    resources: list[Resource] | None = None
    resource_templates: list[ResourceTemplate] | None = None
    prompts: list[Prompt] | None = None

    handshake_complete: bool = False


class ClientSession(BaseSession):
    def __init__(
        self,
        transport: Transport,
        config: ClientConfig,
    ):
        super().__init__(transport)
        self.client_config = config
        self.server_state = ServerState()
        self.callbacks = CallbackManager()

        self.roots = RootsManager()
        self.sampling = SamplingManager()
        self.elicitation = ElicitationManager()
        self._initializing: asyncio.Future[InitializeResult] | None = None

    @property
    def initialized(self) -> bool:
        return self.server_state.handshake_complete

    async def initialize(self, timeout: float = 30.0) -> InitializeResult:
        """Initialize your MCP session with the server.

        Call this once after creating your session—it handles the handshake and
        starts the message loop. Safe to call multiple times. Subsequent calls
        return the cached result.

        Args:
            timeout: How long to wait for the server (seconds).

        Returns:
            Server capabilities and connection details.

        Raises:
            TimeoutError: Server didn't respond in time.
            ValueError: Server uses incompatible protocol version.
            ConnectionError: Connection failed during handshake.
        """
        await self.start()

        if self.server_state.handshake_complete:
            return InitializeResult(
                capabilities=self.server_state.capabilities,
                server_info=self.server_state.info,
                # Server should always use client's protocol version. Otherwise,
                # _do_initialize() will fail.
                protocol_version=self.client_config.protocol_version,
                instructions=self.server_state.instructions,
            )

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
        """Execute the MCP initialization handshake. TODO: Manage server state
        better.

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
        await self.start()
        init_request = InitializeRequest(
            client_info=self.client_config.client_info,
            capabilities=self.client_config.capabilities,
            protocol_version=self.client_config.protocol_version,
        )
        request_id = str(uuid.uuid4())
        jsonrpc_request = JSONRPCRequest.from_request(init_request, request_id)

        # Set up response waiting.
        future: asyncio.Future[Result | Error] = asyncio.Future()
        self._pending_requests[request_id] = (init_request, future)

        try:
            await self.transport.send(jsonrpc_request.to_wire())
            result_or_error = await asyncio.wait_for(future, timeout)
            if isinstance(result_or_error, Error):
                await self.close()
                raise ValueError(f"Initialization failed: {result_or_error.message}")

            init_result = cast(InitializeResult, result_or_error)
            if init_result.protocol_version != self.client_config.protocol_version:
                raise InvalidProtocolVersionError(
                    f"Protocol version mismatch: client version "
                    f"{self.client_config.protocol_version} !="
                    f" server version {init_result.protocol_version}"
                )

            initialized_notification = InitializedNotification()
            await self.send_notification(initialized_notification)

            self.server_state.capabilities = init_result.capabilities
            self.server_state.instructions = init_result.instructions
            self.server_state.info = init_result.server_info
            self.server_state.handshake_complete = True
            return init_result
        except asyncio.TimeoutError:
            await self.close()
            raise TimeoutError(f"Initialization timed out after {timeout}s")
        except InvalidProtocolVersionError as e:
            error = Error(
                code=INVALID_PARAMS,
                message=str(e),
            )
            jsonrpc_error = JSONRPCError.from_error(error, request_id)
            await self.transport.send(jsonrpc_error.to_wire())
            await self.close()
            raise
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

    def _get_request_registry(self) -> dict[str, RequestRegistryEntry]:
        return {
            "ping": (PingRequest, self._handle_ping),
            "roots/list": (ListRootsRequest, self._handle_list_roots),
            "sampling/createMessage": (CreateMessageRequest, self._handle_sampling),
            "elicitation/create": (ElicitRequest, self._handle_elicitation),
        }

    async def _handle_ping(self, request: PingRequest) -> EmptyResult | Error:
        """Handle server request for ping.

        Returns:
            PingResult with pong.
        """
        return EmptyResult()

    async def _handle_list_roots(
        self, request: ListRootsRequest
    ) -> ListRootsResult | Error:
        """Handle server request for filesystem roots.

        Returns available roots if client advertised roots capability,
        otherwise METHOD_NOT_FOUND error.

        Args:
            request: Parsed roots/list request.

        Returns:
            ListRootsResult with roots, or Error if capability missing.
        """
        if self.client_config.capabilities.roots is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support roots capability",
            )
        return await self.roots.handle_list_roots(request)

    async def _handle_sampling(
        self, request: CreateMessageRequest
    ) -> CreateMessageResult | Error:
        if not self.client_config.capabilities.sampling:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support sampling capability",
            )
        try:
            return await self.sampling.handle_create_message(request)
        except SamplingNotConfiguredError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))
        except Exception:
            return Error(code=INTERNAL_ERROR, message="Error in sampling handler")

    async def _handle_elicitation(self, request: ElicitRequest) -> ElicitResult | Error:
        """Handle server request for elicitation."""
        if not self.client_config.capabilities.elicitation:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Client does not support elicitation capability",
            )

        try:
            return await self.elicitation.handle_elicitation(request)
        except ElicitationNotConfiguredError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))
        except Exception:
            return Error(code=INTERNAL_ERROR, message="Error in elicitation handler")

    async def _handle_session_notification(self, payload: dict[str, Any]) -> None:
        method = payload["method"]
        notification_class = NOTIFICATION_REGISTRY.get(method)
        if notification_class is None:
            raise UnknownNotificationError(method)
        notification = notification_class.from_protocol(payload)

        registry = self._get_notification_registry()
        if method in registry:
            handler = registry[method]
            await handler(notification)

    def _get_notification_registry(self) -> dict[str, NotificationHandler]:
        return {
            "notifications/cancelled": self._handle_cancelled,
            "notifications/progress": self._handle_progress,
            "notifications/prompts/list_changed": self._handle_prompts_list_changed,
            "notifications/resources/list_changed": self._handle_resources_list_changed,
            "notifications/resources/updated": self._handle_resources_updated,
            "notifications/tools/list_changed": self._handle_tools_list_changed,
            "notifications/message": self._handle_logging_message,
        }

    async def _handle_cancelled(self, notification: CancelledNotification) -> None:
        if notification.request_id in self._in_flight_requests:
            # Note: Done callback on the request task removes it from the
            # in-flight requests dictionary.
            self._in_flight_requests[notification.request_id].cancel()
        await self.callbacks.notify_cancelled(notification)

    async def _handle_progress(self, notification: ProgressNotification) -> None:
        await self.callbacks.notify_progress(notification)

    async def _handle_prompts_list_changed(
        self, notification: PromptListChangedNotification
    ) -> None:
        result = await self.send_request(ListPromptsRequest())
        if isinstance(result, ListPromptsResult):
            self.server_state.prompts = result.prompts
            await self.callbacks.notify_prompts_changed(result.prompts)

    async def _handle_resources_list_changed(
        self, notification: ResourceListChangedNotification
    ) -> None:
        resources_result = await self.send_request(ListResourcesRequest())
        templates_result = await self.send_request(ListResourceTemplatesRequest())
        if isinstance(resources_result, ListResourcesResult):
            self.server_state.resources = resources_result.resources
            await self.callbacks.notify_resources_changed(resources_result.resources)
        if isinstance(templates_result, ListResourceTemplatesResult):
            self.server_state.resource_templates = templates_result.resource_templates
            await self.callbacks.notify_resource_templates_changed(
                templates_result.resource_templates
            )

    async def _handle_resources_updated(
        self, notification: ResourceUpdatedNotification
    ) -> None:
        resources_result = await self.send_request(ListResourcesRequest())
        templates_result = await self.send_request(ListResourceTemplatesRequest())
        if isinstance(resources_result, ListResourcesResult):
            self.server_state.resources = resources_result.resources
            await self.callbacks.notify_resources_changed(resources_result.resources)
        if isinstance(templates_result, ListResourceTemplatesResult):
            self.server_state.resource_templates = templates_result.resource_templates
            await self.callbacks.notify_resource_templates_changed(
                templates_result.resource_templates
            )

    async def _handle_tools_list_changed(
        self, notification: ToolListChangedNotification
    ) -> None:
        tools_result = await self.send_request(ListToolsRequest())
        if isinstance(tools_result, ListToolsResult):
            self.server_state.tools = tools_result.tools
            await self.callbacks.notify_tools_changed(tools_result.tools)

    async def _handle_logging_message(
        self, notification: LoggingMessageNotification
    ) -> None:
        await self.callbacks.notify_logging_message(notification)

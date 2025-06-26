from typing import Any, Awaitable, Callable, TypeVar

from conduit.protocol.base import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    Error,
    Request,
    Result,
)
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.completions import CompleteRequest, CompleteResult
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializeRequest,
    InitializeResult,
    ServerCapabilities,
)
from conduit.protocol.logging import (
    SetLevelRequest,
)
from conduit.protocol.prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
)
from conduit.protocol.resources import (
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    ReadResourceRequest,
    ReadResourceResult,
    SubscribeRequest,
    UnsubscribeRequest,
)
from conduit.protocol.tools import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
)
from conduit.server.managers.completions import (
    CompletionManager,
    CompletionNotConfiguredError,
)
from conduit.server.managers.logging import LoggingManager
from conduit.server.managers.prompts import PromptManager
from conduit.server.managers.resources import ResourceManager
from conduit.server.managers.tools import ToolManager
from conduit.shared.exceptions import UnknownRequestError
from conduit.shared.session import BaseSession
from conduit.transport.base import Transport

TRequest = TypeVar("TRequest", bound=Request)
TResult = TypeVar("TResult", bound=Result)
RequestHandler = Callable[[TRequest], Awaitable[TResult | Error]]
RequestRegistryEntry = tuple[type[TRequest], RequestHandler[TRequest, TResult]]


class ServerSession(BaseSession):
    def __init__(
        self,
        transport: Transport,
        server_info: Implementation,
        capabilities: ServerCapabilities,
        instructions: str | None = None,
    ):
        super().__init__(transport)
        self.server_info = server_info
        self.capabilities = capabilities
        self._received_initialized_notification = False
        self._client_capabilities: ClientCapabilities | None = None
        self.instructions = instructions

        # Managers
        self.tools = ToolManager()
        self.resources = ResourceManager()
        self.prompts = PromptManager()
        self.logging = LoggingManager()
        self.completions = CompletionManager()

    @property
    def initialized(self) -> bool:
        return self._received_initialized_notification

    def get_client_capabilities(self) -> ClientCapabilities | None:
        return self._client_capabilities

    async def _ensure_can_send_request(self, request: Request) -> None:
        if not self.initialized and not isinstance(request, PingRequest):
            raise RuntimeError(
                "Session must be initialized before sending non-ping requests. "
                "Client must send initialized notification first."
            )

    async def _handle_session_request(self, payload: dict[str, Any]) -> Result | Error:
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
            "initialize": (InitializeRequest, self._handle_initialize),
            "tools/list": (ListToolsRequest, self._handle_list_tools),
            "tools/call": (CallToolRequest, self._handle_call_tool),
            "prompts/list": (ListPromptsRequest, self._handle_list_prompts),
            "prompts/get": (GetPromptRequest, self._handle_get_prompt),
            "resources/list": (ListResourcesRequest, self._handle_list_resources),
            "resources/templates/list": (
                ListResourceTemplatesRequest,
                self._handle_list_resource_templates,
            ),
            "resources/read": (ReadResourceRequest, self._handle_read_resource),
            "resources/subscribe": (SubscribeRequest, self._handle_subscribe),
            "resources/unsubscribe": (UnsubscribeRequest, self._handle_unsubscribe),
            "completion/complete": (CompleteRequest, self._handle_complete),
            "logging/setLevel": (SetLevelRequest, self._handle_set_level),
        }

    async def _handle_ping(self, request: PingRequest) -> EmptyResult | Error:
        return EmptyResult()

    async def _handle_initialize(
        self, request: InitializeRequest
    ) -> InitializeResult | Error:
        self._client_capabilities = request.capabilities
        return InitializeResult(
            capabilities=self.capabilities,
            server_info=self.server_info,
            instructions=self.instructions,
        )

    async def _handle_list_tools(
        self, request: ListToolsRequest
    ) -> ListToolsResult | Error:
        if self.capabilities.tools is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support tools capability",
            )
        return await self.tools.handle_list(request)

    async def _handle_call_tool(
        self, request: CallToolRequest
    ) -> CallToolResult | Error:
        """Handle a tool call request.

        The tool manager will handle tool execution failures and return a
        CallToolResult with is_error=True. Tool execution failures are domain
        errors and should be returned to the LLM for the host to self-correct. If
        the manager does not know about the tool, it will raise a KeyError. We
        catch this and return a method not found error.

        Returns:
            CallToolResult: The result of the tool call. Note we return this even
                if tool execution fails. This is a domain error and should be
                returned to the LLM.
            Error: If the server does not support tools capability or the tool is
                unknown. These are truly exceptional and should be handled by the
                session.
        """
        if self.capabilities.tools is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support tools capability",
            )
        try:
            return await self.tools.handle_call(request)
        except KeyError:
            return Error(code=METHOD_NOT_FOUND, message=f"Unknown tool: {request.name}")

    async def _handle_list_resources(
        self, request: ListResourcesRequest
    ) -> ListResourcesResult | Error:
        if self.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        return await self.resources.handle_list_resources(request)

    async def _handle_list_resource_templates(
        self, request: ListResourceTemplatesRequest
    ) -> ListResourceTemplatesResult | Error:
        if self.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        return await self.resources.handle_list_templates(request)

    async def _handle_read_resource(
        self, request: ReadResourceRequest
    ) -> ReadResourceResult | Error:
        if self.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        try:
            return await self.resources.handle_read(request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Error in resource read handler",
            )

    async def _handle_subscribe(self, request: SubscribeRequest) -> EmptyResult | Error:
        if self.capabilities.resources.subscribe is False or None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resource subscription",
            )

        try:
            return await self.resources.handle_subscribe(request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Error in resource subscribe handler",
            )

    async def _handle_unsubscribe(
        self, request: UnsubscribeRequest
    ) -> EmptyResult | Error:
        if self.capabilities.resources.subscribe is False or None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resource subscription",
            )

        try:
            return await self.resources.handle_unsubscribe(request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Error in resource unsubscribe handler",
            )

    async def _handle_list_prompts(
        self, request: ListPromptsRequest
    ) -> ListPromptsResult | Error:
        if self.capabilities.prompts is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support prompts capability",
            )
        return await self.prompts.handle_list_prompts(request)

    async def _handle_get_prompt(
        self, request: GetPromptRequest
    ) -> GetPromptResult | Error:
        if self.capabilities.prompts is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support prompts capability",
            )
        try:
            return await self.prompts.handle_get_prompt(request)
        except KeyError as e:
            return Error(code=METHOD_NOT_FOUND, message=str(e))
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Error in prompt handler",
            )

    async def _handle_complete(
        self, request: CompleteRequest
    ) -> CompleteResult | Error:
        if self.capabilities.completions is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support completion capability",
            )

        try:
            return await self.completions.handle_complete(request)
        except CompletionNotConfiguredError:
            return Error(
                code=METHOD_NOT_FOUND,
                message="No completion handler registered",
            )
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Error in completion handler",
            )

    async def _handle_set_level(self, request: SetLevelRequest) -> EmptyResult | Error:
        if self.capabilities.logging is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support logging capability",
            )

        try:
            return await self.logging.handle_set_level(request)
        except Exception:
            return Error(
                code=INTERNAL_ERROR,
                message="Error in log level change handler",
            )

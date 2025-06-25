from typing import Any, Awaitable, Callable, TypeVar

from conduit.protocol.base import METHOD_NOT_FOUND, Error, Request, Result
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.completions import CompleteRequest
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializeRequest,
    InitializeResult,
    ServerCapabilities,
)
from conduit.protocol.logging import SetLevelRequest
from conduit.protocol.prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
    Prompt,
)
from conduit.protocol.resources import (
    ListResourcesRequest,
    ListResourcesResult,
    ListResourceTemplatesRequest,
    ListResourceTemplatesResult,
    ReadResourceRequest,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    SubscribeRequest,
    UnsubscribeRequest,
)
from conduit.protocol.tools import (
    CallToolRequest,
    ListToolsRequest,
    ListToolsResult,
    Tool,
)
from conduit.shared.exceptions import UnknownRequestError
from conduit.shared.session import BaseSession
from conduit.transport.base import Transport

T = TypeVar("T", bound=Request)
RequestHandler = Callable[[T], Awaitable[Result | Error]]
RequestRegistryEntry = tuple[type[T], RequestHandler[T]]


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

        # Tool/prompt/resource registries
        self._registered_tools: dict[str, Tool] = {}
        self._registered_prompts: dict[str, Prompt] = {}
        self._registered_resources: dict[str, Resource] = {}
        self._registered_resource_templates: dict[str, ResourceTemplate] = {}

        # Handler registries
        self._resource_handlers: dict[
            str,
            Callable[[ReadResourceRequest], Awaitable[ReadResourceResult]],
        ] = {}
        self._prompt_handlers: dict[
            str,
            Callable[[GetPromptRequest], Awaitable[GetPromptResult]],
        ] = {}

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

    async def _handle_ping(self, request: PingRequest) -> Result | Error:
        return EmptyResult()

    async def _handle_initialize(self, request: InitializeRequest) -> Result | Error:
        self._client_capabilities = request.capabilities
        return InitializeResult(
            capabilities=self.capabilities,
            server_info=self.server_info,
            instructions=self.instructions,
        )

    async def _handle_list_tools(self, request: ListToolsRequest) -> Result | Error:
        if self.capabilities.tools is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support tools capability",
            )
        return ListToolsResult(tools=list(self._registered_tools.values()))

    async def _handle_list_prompts(self, request: ListPromptsRequest) -> Result | Error:
        if self.capabilities.prompts is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support prompts capability",
            )
        return ListPromptsResult(prompts=list(self._registered_prompts.values()))

    async def _handle_list_resources(
        self, request: ListResourcesRequest
    ) -> Result | Error:
        if self.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        return ListResourcesResult(resources=list(self._registered_resources.values()))

    async def _handle_list_resource_templates(
        self, request: ListResourceTemplatesRequest
    ) -> Result | Error:
        if self.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )
        return ListResourceTemplatesResult(
            resource_templates=list(self._registered_resource_templates.values())
        )

    # Handler implementation
    async def _handle_read_resource(
        self, request: ReadResourceRequest
    ) -> Result | Error:
        if self.capabilities.resources is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support resources capability",
            )

        uri = str(request.uri)
        if uri not in self._resource_handlers:
            return Error(
                code=METHOD_NOT_FOUND,
                message=f"Unknown resource: {uri}",
            )

        return await self._resource_handlers[uri](request)

    async def _handle_get_prompt(self, request: GetPromptRequest) -> Result | Error:
        if self.capabilities.prompts is None:
            return Error(
                code=METHOD_NOT_FOUND,
                message="Server does not support prompts capability",
            )

        name = str(request.name)
        if name not in self._prompt_handlers:
            return Error(
                code=METHOD_NOT_FOUND,
                message=f"Unknown prompt: {name}",
            )

        return await self._prompt_handlers[name](request)

    # Registration method
    def register_resource(
        self,
        resource: Resource,
        handler: Callable[[ReadResourceRequest], Awaitable[ReadResourceResult]],
    ) -> None:
        uri = str(resource.uri)
        self._registered_resources[uri] = resource
        self._resource_handlers[uri] = handler

    def register_prompt(
        self,
        prompt: Prompt,
        handler: Callable[[GetPromptRequest], Awaitable[GetPromptResult]],
    ) -> None:
        name = str(prompt.name)
        self._registered_prompts[name] = prompt
        self._prompt_handlers[name] = handler

    def register_tool(
        self, name: str, handler: Callable[[Tool], Result | Error], tool_def: Tool
    ) -> None:
        self._tool_handlers[name] = handler
        self._registered_tools[name] = tool_def

    def _handle_call_tool(self, request: CallToolRequest) -> Result | Error:
        # Capability check and handler execution
        ...

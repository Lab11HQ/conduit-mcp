import logging
from copy import deepcopy
from typing import TYPE_CHECKING, Awaitable, Callable

from conduit.protocol.prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
    Prompt,
)

if TYPE_CHECKING:
    from conduit.server.request_context import RequestContext

PromptHandler = Callable[
    ["RequestContext", GetPromptRequest], Awaitable[GetPromptResult]
]


class PromptManager:
    """Manages protocol prompt registration and execution for a server.

    Controls which prompts are available to MCP clients and how they're executed.
    """

    def __init__(self):
        self.global_prompts: dict[str, Prompt] = {}
        self.global_handlers: dict[str, PromptHandler] = {}
        self.logger = logging.getLogger("conduit.server.protocol.prompts")
        self.client_prompts: dict[
            str, dict[str, Prompt]
        ] = {}  # client_id -> {prompt_name: prompt}
        self.client_handlers: dict[
            str, dict[str, PromptHandler]
        ] = {}  # client_id -> {prompt_name: handler}

    # ================================
    # Global prompt management
    # ================================

    def add_prompt(
        self,
        prompt: Prompt,
        handler: PromptHandler,
    ) -> None:
        """Add a global prompt with its handler function.

        Args:
            prompt: Prompt definition with name, description, and arguments.
            handler: Async function that processes prompt requests. Must take client_id
                and GetPromptRequest as arguments and return a GetPromptResult.
        """
        self.global_prompts[prompt.name] = prompt
        self.global_handlers[prompt.name] = handler

    def get_prompts(self) -> dict[str, Prompt]:
        """Get all global prompts.

        Returns:
            Dictionary mapping prompt names to Prompt objects for all global prompts.
        """
        return deepcopy(self.global_prompts)

    def get_prompt(self, name: str) -> Prompt | None:
        """Get a global prompt by name.

        Args:
            name: Name of the prompt to retrieve.

        Returns:
            Prompt object if found, None otherwise.
        """
        return self.global_prompts.get(name)

    def remove_prompt(self, name: str) -> None:
        """Remove a global prompt by name.

        Args:
            name: Name of the prompt to remove.
        """
        self.global_prompts.pop(name, None)
        self.global_handlers.pop(name, None)

    def clear_prompts(self) -> None:
        """Remove all global prompts and their handlers."""
        self.global_prompts.clear()
        self.global_handlers.clear()

    # ================================
    # Client-specific prompt management
    # ================================

    def add_client_prompt(
        self,
        client_id: str,
        prompt: Prompt,
        handler: PromptHandler,
    ) -> None:
        """Add a prompt for a specific client.

        Overrides global prompts with the same name for this client.

        Args:
            client_id: ID of the client this prompt is specific to.
            prompt: Prompt definition with name, description, and arguments.
            handler: Async function that processes prompt requests. Must take client_id
                and GetPromptRequest as arguments and return a GetPromptResult.
        """
        # Initialize client storage if this is the first prompt for this client
        if client_id not in self.client_prompts:
            self.client_prompts[client_id] = {}
            self.client_handlers[client_id] = {}

        # Store the client-specific prompt and handler
        self.client_prompts[client_id][prompt.name] = prompt
        self.client_handlers[client_id][prompt.name] = handler

    def get_client_prompts(self, client_id: str) -> dict[str, Prompt]:
        """Get all prompts a client can access.

        Returns global prompts plus any client-specific prompts. Client-specific prompts
        override global prompts with the same name.

        Args:
            client_id: ID of the client to get prompts for.

        Returns:
            Dictionary mapping prompt names to Prompt objects for this client.
        """

        # Start with global prompts
        prompts = deepcopy(self.global_prompts)

        # Add client-specific prompts, with override logging
        if client_id in self.client_prompts:
            for name, prompt in self.client_prompts[client_id].items():
                if name in prompts:
                    self.logger.info(
                        f"Client {client_id} overriding global prompt '{name}'"
                    )
                prompts[name] = prompt

        return prompts

    def remove_client_prompt(self, client_id: str, name: str) -> None:
        """Remove a client-specific prompt by name.

        Does not raise an error if the client or prompt doesn't exist.

        Args:
            client_id: ID of the client to remove the prompt from.
            name: Name of the prompt to remove.
        """
        if client_id in self.client_prompts:
            self.client_prompts[client_id].pop(name, None)
            self.client_handlers[client_id].pop(name, None)

    def cleanup_client(self, client_id: str) -> None:
        """Remove all prompts and handlers for a specific client.

        Args:
            client_id: ID of the client to clean up.
        """
        self.client_prompts.pop(client_id, None)
        self.client_handlers.pop(client_id, None)

    # ================================
    # Protocol handlers
    # ================================

    async def handle_list_prompts(
        self, context: "RequestContext", request: ListPromptsRequest
    ) -> ListPromptsResult:
        """List all prompts available to this client.

        Returns all prompts available to this client. Client-specific prompts
        override global prompts with the same name.

        Args:
            context: Request context with client state and helpers
            request: List prompts request with pagination support

        Returns:
            ListPromptsResult: Available prompts for this client
        """
        prompts = self.get_client_prompts(context.client_id)
        return ListPromptsResult(prompts=list(prompts.values()))

    async def handle_get_prompt(
        self, context: "RequestContext", request: GetPromptRequest
    ) -> GetPromptResult:
        """Execute a prompt request for a specific client.

        Uses client-specific handler if available, otherwise falls back to global.

        Args:
            context: Request context with client state and helpers
            request: Get prompt request with name and arguments

        Returns:
            GetPromptResult: Prompt messages from the handler

        Raises:
            KeyError: If the requested prompt is not registered for this client
            Exception: Any exception from the prompt handler
        """
        client_id = context.client_id
        try:
            if (
                client_id in self.client_handlers
                and request.name in self.client_handlers[client_id]
            ):
                handler = self.client_handlers[client_id][request.name]
            elif request.name in self.global_handlers:
                handler = self.global_handlers[request.name]
            else:
                raise KeyError(f"Prompt '{request.name}' not found")

            return await handler(context, request)
        except KeyError:
            raise
        except Exception:
            raise

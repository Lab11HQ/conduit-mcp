from typing import Awaitable, Callable

from conduit.protocol.prompts import (
    GetPromptRequest,
    GetPromptResult,
    ListPromptsRequest,
    ListPromptsResult,
    Prompt,
)


class PromptManager:
    def __init__(self):
        self.registered: dict[str, Prompt] = {}
        self.handlers: dict[
            str, Callable[[GetPromptRequest], Awaitable[GetPromptResult]]
        ] = {}

    def register(
        self,
        prompt: Prompt,
        handler: Callable[[GetPromptRequest], Awaitable[GetPromptResult]],
    ) -> None:
        """Register a prompt with its handler function.

        Your handler should process request arguments and return GetPromptResult
        with appropriate messages. Handler exceptions become INTERNAL_ERROR responses,
        so consider handling expected failures gracefully within your handler.

        Args:
            prompt: Prompt definition with name, description, and arguments.
            handler: Async function that processes prompt requests. Should return
                GetPromptResult with messages for the LLM.
        """
        name = str(prompt.name)
        self.registered[name] = prompt
        self.handlers[name] = handler

    async def handle_list_prompts(
        self, request: ListPromptsRequest
    ) -> ListPromptsResult:
        """List all registered prompts.

        Ignores pagination parameters for now - returns all prompts.
        Future versions can handle cursor, limit, and filtering.

        Args:
            request: List prompts request with optional pagination.

        Returns:
            ListPromptsResult: All registered prompts.
        """
        return ListPromptsResult(prompts=list(self.registered.values()))

    async def handle_get_prompt(self, request: GetPromptRequest) -> GetPromptResult:
        """Execute a registered prompt handler with the given arguments.

        Your prompt handler should process the request arguments and return
        GetPromptResult with appropriate messages. Handler exceptions bubble up
        to the session for protocol error conversion.

        Args:
            request: Get prompt request with name and arguments.

        Returns:
            GetPromptResult: Prompt messages from the handler.

        Raises:
            KeyError: If the requested prompt is not registered.
            Exception: Any exception from the prompt handler.
        """
        name = str(request.name)

        if name not in self.handlers:
            raise KeyError(f"Unknown prompt: {name}")

        try:
            return await self.handlers[name](request)
        except Exception:
            # Re-raise handler failures for session to convert to protocol errors
            raise

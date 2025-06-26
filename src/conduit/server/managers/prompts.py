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
        """Register a prompt with its handler."""
        name = str(prompt.name)
        self.registered[name] = prompt
        self.handlers[name] = handler

    async def handle_list_prompts(
        self, request: ListPromptsRequest
    ) -> ListPromptsResult:
        """Handle list prompts request with pagination support."""
        return ListPromptsResult(prompts=list(self.registered.values()))

    async def handle_get_prompt(self, request: GetPromptRequest) -> GetPromptResult:
        """Handle get prompt request. Raises KeyError if prompt not found."""
        name = str(request.name)

        if name not in self.handlers:
            raise KeyError(f"Unknown prompt: {name}")

        return await self.handlers[name](request)

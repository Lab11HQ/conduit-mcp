from typing import Awaitable, Callable

from conduit.protocol.completions import CompleteRequest, CompleteResult


class CompletionNotConfiguredError(Exception):
    """Raised when completion is requested but no handler is configured."""

    pass


class CompletionManager:
    def __init__(self):
        self.handler: Callable[[CompleteRequest], Awaitable[CompleteResult]] | None = (
            None
        )

    def set_handler(
        self, handler: Callable[[CompleteRequest], Awaitable[CompleteResult]]
    ) -> None:
        """Set the completion handler for all completion requests."""
        self.handler = handler

    async def handle_complete(self, request: CompleteRequest) -> CompleteResult:
        """Handle completion request."""
        if self.handler is None:
            raise CompletionNotConfiguredError("No completion handler registered")
        return await self.handler(request)

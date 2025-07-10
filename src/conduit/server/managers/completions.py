from typing import Awaitable, Callable

from conduit.protocol.completions import CompleteRequest, CompleteResult


class CompletionNotConfiguredError(Exception):
    """Raised when completion is requested but no handler is configured."""

    pass


class CompletionManager:
    def __init__(self):
        self.handler: (
            Callable[[str, CompleteRequest], Awaitable[CompleteResult]] | None
        ) = None

    def set_handler(
        self,
        handler: Callable[[str, CompleteRequest], Awaitable[CompleteResult]],
    ) -> None:
        """Set the completion handler for all completion requests."""
        self.handler = handler

    async def handle_complete(
        self, client_id: str, request: CompleteRequest
    ) -> CompleteResult:
        """Generate completions using the configured handler.

        Delegates to the registered completion handler for actual generation.
        The handler should process the request reference and arguments to
        produce appropriate completions.

        Args:
            request: Complete request with reference and arguments.
            client_id: The client's unique identifier.

        Returns:
            CompleteResult: Generated completion from the handler.

        Raises:
            CompletionNotConfiguredError: If no completion handler is set.
            Exception: Any exception from the completion handler.
        """
        if self.handler is None:
            raise CompletionNotConfiguredError("No completion handler registered")
        return await self.handler(client_id, request)

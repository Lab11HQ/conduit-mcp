import logging
from typing import Awaitable, Callable

from conduit.protocol.completions import CompleteRequest, CompleteResult


class CompletionNotConfiguredError(Exception):
    """Raised when completion is requested but no handler is configured."""

    pass


class CompletionManager:
    def __init__(self):
        self.completion_handler: (
            Callable[[str, CompleteRequest], Awaitable[CompleteResult]] | None
        ) = None
        self.logger = logging.getLogger("conduit.server.protocol.completions")

    async def handle_complete(
        self, client_id: str, request: CompleteRequest
    ) -> CompleteResult:
        """Calls the completion handler.

        Args:
            client_id: The client's unique identifier.
            request: Complete request with reference and arguments.

        Returns:
            CompleteResult: Generated completion from the handler.

        Raises:
            CompletionNotConfiguredError: If no completion handler is set.
            Exception: Any exception from the completion handler.
        """
        if self.completion_handler is None:
            raise CompletionNotConfiguredError("No completion handler registered")
        return await self.completion_handler(client_id, request)

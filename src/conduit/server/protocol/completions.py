import logging
from typing import TYPE_CHECKING, Awaitable, Callable

from conduit.protocol.completions import CompleteRequest, CompleteResult

if TYPE_CHECKING:
    from conduit.server.request_context import RequestContext


class CompletionNotConfiguredError(Exception):
    """Raised when completion is requested but no handler is configured."""


class CompletionManager:
    def __init__(self):
        self.completion_handler: (
            Callable[["RequestContext", CompleteRequest], Awaitable[CompleteResult]]
            | None
        ) = None
        self.logger = logging.getLogger("conduit.server.protocol.completions")

    async def handle_complete(
        self, context: "RequestContext", request: CompleteRequest
    ) -> CompleteResult:
        """Generate a completion for a given argument.

        Args:
            context: Rich request context with client state and helpers
            request: Complete request with reference and arguments.

        Returns:
            CompleteResult: Generated completion from the handler.

        Raises:
            CompletionNotConfiguredError: If no completion handler is set.
            Exception: Any exception from the completion handler.
        """
        if self.completion_handler is None:
            raise CompletionNotConfiguredError("No completion handler registered")
        return await self.completion_handler(context, request)

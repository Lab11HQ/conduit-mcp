import logging
from typing import Awaitable, Callable

from conduit.client.request_context import RequestContext
from conduit.protocol.elicitation import ElicitRequest, ElicitResult


class ElicitationNotConfiguredError(Exception):
    """Raised when elicitation is requested but no handler is configured."""

    pass


class ElicitationManager:
    def __init__(self):
        self.elicitation_handler: (
            Callable[[ElicitRequest], Awaitable[ElicitResult]] | None
        ) = None
        self.logger = logging.getLogger("conduit.client.protocol.elicitation")

    async def handle_elicitation(
        self, context: RequestContext, request: ElicitRequest
    ) -> ElicitResult:
        """Elicit a response from the user.

        Args:
            context: The request context with server state and helpers.
            request: The elicitation request.

        Returns:
            The elicitation result.

        Raises:
            ElicitationNotConfiguredError: If no elicitation handler is registered.
            Exception: If the elicitation handler raises an exception.
        """
        if self.elicitation_handler is None:
            raise ElicitationNotConfiguredError("No elicitation handler registered")
        return await self.elicitation_handler(request)

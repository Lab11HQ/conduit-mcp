import logging
from typing import Awaitable, Callable

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
        self, server_id: str, request: ElicitRequest
    ) -> ElicitResult:
        """Calls the elicitation handler.

        Args:
            server_id: The server ID.
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

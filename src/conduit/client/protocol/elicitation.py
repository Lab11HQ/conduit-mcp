from typing import Awaitable, Callable

from conduit.protocol.elicitation import ElicitRequest, ElicitResult


class ElicitationNotConfiguredError(Exception):
    """Raised when elicitation is requested but no handler is configured."""

    pass


class ElicitationManager:
    def __init__(self):
        # Direct callback assignment
        self.elicitation_handler: (
            Callable[[ElicitRequest], Awaitable[ElicitResult]] | None
        ) = None

    async def handle_elicitation(
        self, server_id: str, request: ElicitRequest
    ) -> ElicitResult:
        if self.elicitation_handler is None:
            raise ElicitationNotConfiguredError("No elicitation handler registered")
        return await self.elicitation_handler(request)

from typing import Awaitable, Callable

from conduit.protocol.elicitation import ElicitRequest, ElicitResult


class ElicitationNotConfiguredError(Exception):
    """Raised when elicitation is requested but no handler is configured."""

    pass


class ElicitationManager:
    def __init__(self):
        self._handler: Callable[[ElicitRequest], Awaitable[ElicitResult]] | None = None

    def set_handler(
        self, handler: Callable[[ElicitRequest], Awaitable[ElicitResult]]
    ) -> None:
        self._handler = handler

    async def handle_elicitation(
        self, server_id: str, request: ElicitRequest
    ) -> ElicitResult:
        if self._handler is None:
            raise ElicitationNotConfiguredError("No elicitation handler registered")
        return await self._handler(request)

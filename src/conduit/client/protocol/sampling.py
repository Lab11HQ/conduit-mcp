from typing import Awaitable, Callable

from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult


class SamplingNotConfiguredError(Exception):
    """Raised when sampling is requested but no handler is configured."""

    pass


class SamplingManager:
    def __init__(self):
        self._handler: (
            Callable[[CreateMessageRequest], Awaitable[CreateMessageResult]] | None
        ) = None

    def set_handler(
        self, handler: Callable[[CreateMessageRequest], Awaitable[CreateMessageResult]]
    ) -> None:
        """Register a handler for sampling/createMessage requests."""
        self._handler = handler

    async def handle_create_message(
        self, server_id: str, request: CreateMessageRequest
    ) -> CreateMessageResult:
        """Handle create message request.

        Raises:
            SamplingNotConfiguredError: If no handler registered.
        """
        if self._handler is None:
            raise SamplingNotConfiguredError("No sampling handler registered")
        return await self._handler(request)

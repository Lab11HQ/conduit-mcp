from typing import Awaitable, Callable

from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult


class SamplingNotConfiguredError(Exception):
    """Raised when sampling is requested but no handler is configured."""

    pass


class SamplingManager:
    def __init__(self):
        # Direct callback assignment
        self.sampling_handler: (
            Callable[[CreateMessageRequest], Awaitable[CreateMessageResult]] | None
        ) = None

    async def handle_create_message(
        self, server_id: str, request: CreateMessageRequest
    ) -> CreateMessageResult:
        """Handle create message request.

        Raises:
            SamplingNotConfiguredError: If no handler registered.
        """
        if self.sampling_handler is None:
            raise SamplingNotConfiguredError("No sampling handler registered")
        return await self.sampling_handler(request)

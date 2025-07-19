from typing import Awaitable, Callable

from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult


class SamplingNotConfiguredError(Exception):
    """Raised when sampling is requested but no handler is configured."""

    pass


class SamplingManager:
    def __init__(self):
        self.sampling_handler: (
            Callable[[CreateMessageRequest], Awaitable[CreateMessageResult]] | None
        ) = None

    async def handle_create_message(
        self, server_id: str, request: CreateMessageRequest
    ) -> CreateMessageResult:
        """Calls the sampling handler.

        Args:
            server_id: The server ID.
            request: The create message request.

        Returns:
            The create message result.
        Raises:
            SamplingNotConfiguredError: If no handler is registered.
            Exception: If the sampling handler raises an exception.
        """
        if self.sampling_handler is None:
            raise SamplingNotConfiguredError("No sampling handler registered")
        return await self.sampling_handler(request)

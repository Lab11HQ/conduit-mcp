import logging
from typing import Awaitable, Callable

from conduit.client.request_context import RequestContext
from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult


class SamplingNotConfiguredError(Exception):
    """Raised when sampling is requested but no handler is configured."""

    pass


class SamplingManager:
    def __init__(self):
        self.sampling_handler: (
            Callable[[CreateMessageRequest], Awaitable[CreateMessageResult]] | None
        ) = None
        self.logger = logging.getLogger("conduit.client.protocol.sampling")

    async def handle_create_message(
        self, context: RequestContext, request: CreateMessageRequest
    ) -> CreateMessageResult:
        """Sample the host LLM for the server.

        Args:
            context: The request context with server state and helpers.
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

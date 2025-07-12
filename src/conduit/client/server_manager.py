import asyncio
from dataclasses import dataclass, field

from conduit.protocol.base import INTERNAL_ERROR, Error, Request, Result
from conduit.protocol.initialization import Implementation, ServerCapabilities
from conduit.protocol.prompts import Prompt
from conduit.protocol.resources import Resource, ResourceTemplate
from conduit.protocol.tools import Tool


@dataclass
class ServerContext:
    """Complete server state in one place."""

    # Protocol state
    capabilities: ServerCapabilities | None = None
    info: Implementation | None = None
    protocol_version: str | None = None
    instructions: str | None = None
    initialized: bool = False

    # Domain state
    tools: list[Tool] | None = None
    resources: list[Resource] | None = None
    resource_templates: list[ResourceTemplate] | None = None
    prompts: list[Prompt] | None = None

    # Request tracking
    requests_from_server: dict[str | int, asyncio.Task[None]] = field(
        default_factory=dict
    )
    requests_to_server: dict[
        str | int, tuple[Request, asyncio.Future[Result | Error]]
    ] = field(default_factory=dict)


class ServerManager:
    """Owns all server state and lifecycle."""

    def __init__(self):
        self._server_context = ServerContext()

    def get_server_context(self) -> ServerContext:
        """Get the server context."""
        return self._server_context

    def cleanup_requests(self) -> None:
        """Clean up all request tracking when stopping.

        Cancels in-flight requests the server is waiting on and resolves pending
        requests the server is fulfilling.
        """
        context = self._server_context

        for task in context.requests_from_server.values():
            task.cancel()
        context.requests_from_server.clear()

        for _, future in context.requests_to_server.values():
            if not future.done():
                error = Error(
                    code=INTERNAL_ERROR,
                    message="Request failed. Client coordinator stopped.",
                )
                future.set_result(error)
        context.requests_to_server.clear()

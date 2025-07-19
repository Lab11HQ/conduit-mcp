from typing import Awaitable, Callable

from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.protocol.logging import LoggingMessageNotification
from conduit.protocol.prompts import (
    Prompt,
)
from conduit.protocol.resources import (
    ReadResourceResult,
    Resource,
    ResourceTemplate,
)
from conduit.protocol.tools import (
    Tool,
)


class CallbackManager:
    """Manages event callbacks for server state changes."""

    def __init__(self):
        # Direct callback assignment
        self.progress_handler: (
            Callable[[ProgressNotification], Awaitable[None]] | None
        ) = None
        self.tools_changed_handler: Callable[[list[Tool]], Awaitable[None]] | None = (
            None
        )
        self.resources_changed_handler: (
            Callable[[list[Resource], list[ResourceTemplate]], Awaitable[None]] | None
        ) = None
        self.resource_updated_handler: (
            Callable[[str, ReadResourceResult], Awaitable[None]] | None
        ) = None
        self.prompts_changed_handler: (
            Callable[[list[Prompt]], Awaitable[None]] | None
        ) = None
        self.logging_message_handler: (
            Callable[[LoggingMessageNotification], Awaitable[None]] | None
        ) = None
        self.cancelled_handler: (
            Callable[[CancelledNotification], Awaitable[None]] | None
        ) = None

    async def call_progress(
        self, server_id: str, notification: ProgressNotification
    ) -> None:
        """Invoke progress callback with the notification."""
        if self.progress_handler:
            try:
                await self.progress_handler(notification)
            except Exception as e:
                print(f"Progress callback failed: {e}")

    async def call_cancelled(
        self, server_id: str, notification: CancelledNotification
    ) -> None:
        """Invoke cancelled callback with the notification."""
        if self.cancelled_handler:
            try:
                await self.cancelled_handler(notification)
            except Exception as e:
                print(f"Cancelled callback failed: {e}")

    async def call_tools_changed(self, server_id: str, tools: list[Tool]) -> None:
        """Invoke tools changed callback with the updated tools."""
        if self.tools_changed_handler:
            try:
                await self.tools_changed_handler(tools)
            except Exception as e:
                print(f"Tools changed callback failed: {e}")

    async def call_resources_changed(
        self,
        server_id: str,
        resources: list[Resource],
        templates: list[ResourceTemplate],
    ) -> None:
        """Invoke resources changed callback."""
        if self.resources_changed_handler:
            try:
                await self.resources_changed_handler(resources, templates)
            except Exception as e:
                print(f"Resources changed callback failed: {e}")

    async def call_resource_updated(
        self, server_id: str, uri: str, result: ReadResourceResult
    ) -> None:
        """Invoke resource updated callback with URI and result."""
        if self.resource_updated_handler:
            try:
                await self.resource_updated_handler(uri, result)
            except Exception as e:
                print(f"Resource updated callback failed: {e}")

    async def call_prompts_changed(self, server_id: str, prompts: list[Prompt]) -> None:
        """Invoke prompts changed callback with the updated prompts."""
        if self.prompts_changed_handler:
            try:
                await self.prompts_changed_handler(prompts)
            except Exception as e:
                print(f"Prompts changed callback failed: {e}")

    async def call_logging_message(
        self, server_id: str, notification: LoggingMessageNotification
    ) -> None:
        """Invoke logging message callback with the notification."""
        if self.logging_message_handler:
            try:
                await self.logging_message_handler(notification)
            except Exception as e:
                print(f"Logging message callback failed: {e}")

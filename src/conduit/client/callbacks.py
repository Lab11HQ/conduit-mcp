import logging
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
        self.logger = logging.getLogger("conduit.client.callbacks")

    async def call_progress(
        self, server_id: str, notification: ProgressNotification
    ) -> None:
        """Invokes progress callback. Catches and logs any errors."""
        if self.progress_handler:
            try:
                await self.progress_handler(notification)
            except Exception as e:
                self.logger.warning(
                    f"Progress callback failed: {e}. "
                    f"Server: {server_id}. "
                    f"Notification: {notification}"
                )

    async def call_cancelled(
        self, server_id: str, notification: CancelledNotification
    ) -> None:
        """Invokes cancelled callback. Catches and logs any errors."""
        if self.cancelled_handler:
            try:
                await self.cancelled_handler(notification)
            except Exception as e:
                self.logger.warning(
                    f"Cancelled callback failed: {e}. "
                    f"Server: {server_id}. "
                    f"Notification: {notification}"
                )

    async def call_tools_changed(self, server_id: str, tools: list[Tool]) -> None:
        """Invokes tools changed callback. Catches and logs any errors."""
        if self.tools_changed_handler:
            try:
                await self.tools_changed_handler(tools)
            except Exception as e:
                self.logger.warning(
                    f"Tools changed callback failed: {e}. "
                    f"Server: {server_id}. "
                    f"Tools: {tools}"
                )

    async def call_resources_changed(
        self,
        server_id: str,
        resources: list[Resource],
        templates: list[ResourceTemplate],
    ) -> None:
        """Invokes resources changed callback. Catches and logs any errors."""
        if self.resources_changed_handler:
            try:
                await self.resources_changed_handler(resources, templates)
            except Exception as e:
                self.logger.warning(
                    f"Resources changed callback failed: {e}. "
                    f"Server: {server_id}. "
                    f"Resources: {resources}. "
                    f"Templates: {templates}"
                )

    async def call_resource_updated(
        self, server_id: str, uri: str, result: ReadResourceResult
    ) -> None:
        """Invokes resource updated callback. Catches and logs any errors."""
        if self.resource_updated_handler:
            try:
                await self.resource_updated_handler(uri, result)
            except Exception as e:
                self.logger.warning(
                    f"Resource updated callback failed: {e}. "
                    f"Server: {server_id}. "
                    f"URI: {uri}. "
                    f"Result: {result}"
                )

    async def call_prompts_changed(self, server_id: str, prompts: list[Prompt]) -> None:
        """Invokes prompts changed callback. Catches and logs any errors."""
        if self.prompts_changed_handler:
            try:
                await self.prompts_changed_handler(prompts)
            except Exception as e:
                self.logger.warning(
                    f"Prompts changed callback failed: {e}. "
                    f"Server: {server_id}. "
                    f"Prompts: {prompts}"
                )

    async def call_logging_message(
        self, server_id: str, notification: LoggingMessageNotification
    ) -> None:
        """Invokes logging message callback. Catches and logs any errors."""
        if self.logging_message_handler:
            try:
                await self.logging_message_handler(notification)
            except Exception as e:
                self.logger.warning(
                    f"Logging message callback failed: {e}. "
                    f"Server: {server_id}. "
                    f"Notification: {notification}"
                )

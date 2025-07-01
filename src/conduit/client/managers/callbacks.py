from typing import Awaitable, Callable

from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.protocol.logging import LoggingMessageNotification
from conduit.protocol.prompts import (
    Prompt,
)
from conduit.protocol.resources import (
    Resource,
    ResourceTemplate,
)
from conduit.protocol.tools import (
    Tool,
)


class CallbackManager:
    """Manages event callbacks for server state changes."""

    def __init__(self):
        self._progress: Callable[[ProgressNotification], Awaitable[None]] | None = None
        self._tools_changed: Callable[[list[Tool]], Awaitable[None]] | None = None
        self._resources_changed: Callable[[list[Resource]], Awaitable[None]] | None = (
            None
        )
        self._resource_templates_changed: (
            Callable[[list[ResourceTemplate]], Awaitable[None]] | None
        ) = None
        self._prompts_changed: Callable[[list[Prompt]], Awaitable[None]] | None = None
        self._logging_message: (
            Callable[[LoggingMessageNotification], Awaitable[None]] | None
        ) = None
        self._cancelled: Callable[[CancelledNotification], Awaitable[None]] | None = (
            None
        )

    def on_progress(
        self, callback: Callable[[ProgressNotification], Awaitable[None]]
    ) -> None:
        """Register callback for progress notifications."""
        self._progress = callback

    def on_tools_changed(
        self, callback: Callable[[list[Tool]], Awaitable[None]]
    ) -> None:
        """Register callback for when server tools change."""
        self._tools_changed = callback

    def on_resources_changed(
        self, callback: Callable[[list[Resource]], Awaitable[None]]
    ) -> None:
        """Register callback for when server resources change."""
        self._resources_changed = callback

    def on_resource_templates_changed(
        self, callback: Callable[[list[ResourceTemplate]], Awaitable[None]]
    ) -> None:
        """Register callback for when server resource templates change."""
        self._resource_templates_changed = callback

    def on_prompts_changed(
        self, callback: Callable[[list[Prompt]], Awaitable[None]]
    ) -> None:
        """Register callback for when server prompts change."""
        self._prompts_changed = callback

    def on_logging_message(
        self, callback: Callable[[LoggingMessageNotification], Awaitable[None]]
    ) -> None:
        """Register callback for server logging messages."""
        self._logging_message = callback

    def on_cancelled(
        self, callback: Callable[[CancelledNotification], Awaitable[None]]
    ) -> None:
        """Register callback for when server cancels a request."""
        self._cancelled = callback

    # Internal notification methods
    async def call_progress(self, notification: ProgressNotification) -> None:
        if self._progress:
            try:
                await self._progress(notification)
            except Exception as e:
                print(f"Progress callback failed: {e}")

    async def call_tools_changed(self, tools: list[Tool]) -> None:
        if self._tools_changed:
            try:
                await self._tools_changed(tools)
            except Exception as e:
                print(f"Tools changed callback failed: {e}")

    async def call_resources_changed(self, resources: list[Resource]) -> None:
        if self._resources_changed:
            try:
                await self._resources_changed(resources)
            except Exception as e:
                print(f"Resources changed callback failed: {e}")

    async def call_resource_templates_changed(
        self, templates: list[ResourceTemplate]
    ) -> None:
        if self._resource_templates_changed:
            try:
                await self._resource_templates_changed(templates)
            except Exception as e:
                print(f"Resource templates changed callback failed: {e}")

    async def call_prompts_changed(self, prompts: list[Prompt]) -> None:
        if self._prompts_changed:
            try:
                await self._prompts_changed(prompts)
            except Exception as e:
                print(f"Prompts changed callback failed: {e}")

    async def call_logging_message(
        self, notification: LoggingMessageNotification
    ) -> None:
        if self._logging_message:
            try:
                await self._logging_message(notification)
            except Exception as e:
                print(f"Logging message callback failed: {e}")

    async def call_cancelled(self, notification: CancelledNotification) -> None:
        if self._cancelled:
            try:
                await self._cancelled(notification)
            except Exception as e:
                print(f"Cancelled callback failed: {e}")

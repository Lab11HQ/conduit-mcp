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
        self._progress: Callable[[ProgressNotification], Awaitable[None]] | None = None
        self._tools_changed: Callable[[list[Tool]], Awaitable[None]] | None = None
        self._resources_changed: (
            Callable[[list[Resource], list[ResourceTemplate]], Awaitable[None]] | None
        ) = None
        self._resource_updated: (
            Callable[[str, ReadResourceResult], Awaitable[None]] | None
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
        """Register your callback for server progress updates.

        Your callback receives the complete notification with all progress
        details - current amount, total expected, status messages, and the
        token identifying which operation is progressing.

        Args:
            callback: Your async function called with each ProgressNotification.
                Gets progress_token, progress, total (optional), and message
                (optional) fields.
        """
        self._progress = callback

    async def call_progress(self, notification: ProgressNotification) -> None:
        """Invoke your registered progress callback with the notification.

        Calls your progress callback if you've registered one. Logs any errors
        that occur.

        Args:
            notification: Progress notification to pass through to your callback.
        """
        if self._progress:
            try:
                await self._progress(notification)
            except Exception as e:
                print(f"Progress callback failed: {e}")

    def on_tools_changed(
        self, callback: Callable[[list[Tool]], Awaitable[None]]
    ) -> None:
        """Register your callback for when server tools change.

        Servers send a signal when their tool catalog changes - tools added,
        removed, or modified. We automatically fetch the updated list and
        call your callback with the new list.

        Args:
            callback: Your async function called with the new list of tools
                whenever the server's tool catalog changes.
        """
        self._tools_changed = callback

    async def call_tools_changed(self, tools: list[Tool]) -> None:
        """Invoke your registered tools changed callback with the updated tools.

        Calls your tools callback if you've registered one. Logs any errors
        that occur.

        Args:
            tools: Current tools list to pass through to your callback.
        """
        if self._tools_changed:
            try:
                await self._tools_changed(tools)
            except Exception as e:
                print(f"Tools changed callback failed: {e}")

    def on_resources_changed(
        self,
        callback: Callable[[list[Resource], list[ResourceTemplate]], Awaitable[None]],
    ) -> None:
        """Register your callback for when server resources change.

        Servers send a signal when their resource catalog changes - resources
        added, removed, or modified. We automatically fetch both the updated
        resources list and resource templates, then call your callback with both.

        Args:
            callback: Your async function called with (resources, templates)
                     whenever the server's resource catalog changes.
        """
        self._resources_changed = callback

    async def call_resources_changed(
        self, resources: list[Resource], templates: list[ResourceTemplate]
    ) -> None:
        """Invoke your registered resources callback.

        Calls your resources callback if you've registered one. Logs any errors
        that occur.

        Args:
            resources: Current resources list to pass through to your callback.
            templates: Current resource templates list to pass through to your callback.
        """
        if self._resources_changed:
            try:
                await self._resources_changed(resources, templates)
            except Exception as e:
                print(f"Resources changed callback failed: {e}")

    def on_resource_updated(
        self, callback: Callable[[str, ReadResourceResult], Awaitable[None]]
    ) -> None:
        """Register your callback for when a specific resource is updated.

        Servers send notifications when individual resources change. We
        automatically read the updated resource content and call your callback
        with both the resource URI and the fresh data.

        Args:
            callback: Your async function called with (uri, result) when a
                resource is updated. Gets the resource URI string and
                ReadResourceResult with the updated content.
        """
        self._resource_updated = callback

    async def call_resource_updated(self, uri: str, result: ReadResourceResult) -> None:
        """Invoke your registered resource updated callback with URI and result.

        Calls your resource updated callback if you've registered one. Logs any
        errors that occur.

        Args:
            uri: Resource URI that was updated.
            result: Fresh resource data from the server.
        """
        if self._resource_updated:
            try:
                await self._resource_updated(uri, result)
            except Exception as e:
                print(f"Resource updated callback failed: {e}")

    def on_prompts_changed(
        self, callback: Callable[[list[Prompt]], Awaitable[None]]
    ) -> None:
        """Register your callback for when server prompts change.

        Servers send a signal when their prompt catalog changes - prompts
        added, removed, or modified. We automatically fetch the updated prompts
        list and call your callback with the current prompts.

        Args:
            callback: Your async function called with the updated list[Prompt]
                whenever the server's prompt catalog changes.
        """
        self._prompts_changed = callback

    async def call_prompts_changed(self, prompts: list[Prompt]) -> None:
        """Invoke your registered prompts changed callback with the updated prompts.

        Calls your prompts callback if you've registered one. Logs any errors
        that occur.

        Args:
            prompts: Current prompts list to pass through to your callback.
        """
        if self._prompts_changed:
            try:
                await self._prompts_changed(prompts)
            except Exception as e:
                print(f"Prompts changed callback failed: {e}")

    def on_logging_message(
        self, callback: Callable[[LoggingMessageNotification], Awaitable[None]]
    ) -> None:
        """Register your callback for server logging messages.

        Servers send log messages during operations to provide debugging
        information and status updates. Your callback receives the complete
        notification with all logging details.

        Args:
            callback: Your async function called with each LoggingMessageNotification.
                Gets level, data, and logger (optional) fields.
        """
        self._logging_message = callback

    async def call_logging_message(
        self, notification: LoggingMessageNotification
    ) -> None:
        """Invoke your registered logging message callback with the notification.

        Calls your logging callback if you've registered one. Logs any errors
        that occur.

        Args:
            notification: Logging notification to pass through to your callback.
        """
        if self._logging_message:
            try:
                await self._logging_message(notification)
            except Exception as e:
                print(f"Logging message callback failed: {e}")

    def on_cancelled(
        self, callback: Callable[[CancelledNotification], Awaitable[None]]
    ) -> None:
        """Register your callback for when the server cancels a request.

        Your callback receives the complete notification with
        cancellation details. Only called if the request was successfully
        cancelled.

        Args:
            callback: Your async function called with each CancelledNotification.
                Gets request_id and reason (optional) fields.
        """
        self._cancelled = callback

    async def call_cancelled(self, notification: CancelledNotification) -> None:
        """Invoke your registered cancelled callback with the notification.

        Calls your cancelled callback if you've registered one. Logs any errors
        that occur.

        Args:
            notification: Cancellation notification to pass through to your callback.
        """
        if self._cancelled:
            try:
                await self._cancelled(notification)
            except Exception as e:
                print(f"Cancelled callback failed: {e}")

    # Internal notification methods

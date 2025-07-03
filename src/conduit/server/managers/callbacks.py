from typing import Awaitable, Callable

from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.protocol.roots import Root


class CallbackManager:
    """Manages event callbacks for client state changes."""

    def __init__(self):
        self._initialized: Callable[[], Awaitable[None]] | None = None
        self._progress: Callable[[ProgressNotification], Awaitable[None]] | None = None
        self._roots_changed: Callable[[list[Root]], Awaitable[None]] | None = None
        self._cancelled: Callable[[CancelledNotification], Awaitable[None]] | None = (
            None
        )

    def on_initialized(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Register callback for when client completes initialization."""
        self._initialized = callback

    async def call_initialized(self) -> None:
        """Call your registered initialization callback."""
        if self._initialized:
            try:
                await self._initialized()
            except Exception as e:
                print(f"Initialization callback failed: {e}")

    def on_progress(
        self, callback: Callable[[ProgressNotification], Awaitable[None]]
    ) -> None:
        """Register callback for client progress notifications."""
        self._progress = callback

    def on_roots_changed(
        self, callback: Callable[[list[Root]], Awaitable[None]]
    ) -> None:
        """Register callback for when client roots change."""
        self._roots_changed = callback

    def on_cancelled(
        self, callback: Callable[[CancelledNotification], Awaitable[None]]
    ) -> None:
        """Register your callback for when server cancels a request.

        Your callback receives the complete notification with
        cancellation details - which request was cancelled and why.

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
    async def notify_progress(self, notification: ProgressNotification) -> None:
        if self._progress:
            await self._progress(notification)

    async def notify_roots_changed(self, roots: list[Root]) -> None:
        if self._roots_changed:
            await self._roots_changed(roots)

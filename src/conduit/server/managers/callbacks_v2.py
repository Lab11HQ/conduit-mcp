from typing import Awaitable, Callable

from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.protocol.roots import Root


class CallbackManager:
    """Manages event callbacks for client state changes."""

    def __init__(self):
        self._initialized: Callable[[], Awaitable[None]] | None = None
        self._progress: Callable[[ProgressNotification], Awaitable[None]] | None = None
        self._roots_changed: Callable[[list[Root]], Awaitable[None]] | None = None
        self._cancelled: (
            Callable[[str, CancelledNotification], Awaitable[None]] | None
        ) = None

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
        """Register your callback for when server sends progress updates.

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

    def on_roots_changed(
        self, callback: Callable[[list[Root]], Awaitable[None]]
    ) -> None:
        """Register your callback for when client roots change.

        Your callback receives the complete list of roots that the client
        has access to.

        Args:
            callback: Your async function called with the new list of roots.
        """
        self._roots_changed = callback

    async def call_roots_changed(self, roots: list[Root]) -> None:
        """Invoke your registered roots changed callback with the roots.

        Calls your roots changed callback if you've registered one. Logs any
        errors that occur.

        Args:
            roots: Current roots list to pass through to your callback.
        """
        if self._roots_changed:
            try:
                await self._roots_changed(roots)
            except Exception as e:
                print(f"Roots changed callback failed: {e}")

    def on_cancelled(
        self, callback: Callable[[str, CancelledNotification], Awaitable[None]]
    ) -> None:
        """Register callback for cancellation notifications with client context."""
        self._cancelled = callback

    async def call_cancelled(
        self, client_id: str, notification: CancelledNotification
    ) -> None:
        """Invoke cancelled callback with client context."""
        if self._cancelled:
            try:
                await self._cancelled(client_id, notification)
            except Exception as e:
                print(f"Cancelled callback failed for {client_id}: {e}")

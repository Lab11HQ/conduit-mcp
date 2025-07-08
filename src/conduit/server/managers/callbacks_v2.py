from typing import Awaitable, Callable

from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.protocol.roots import Root


class CallbackManager:
    """Manages event callbacks for client state changes."""

    def __init__(self):
        self._initialized: Callable[[], Awaitable[None]] | None = None
        self._progress: (
            Callable[[str, ProgressNotification], Awaitable[None]] | None
        ) = None
        self._roots_changed: Callable[[str, list[Root]], Awaitable[None]] | None = None
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
        self, callback: Callable[[str, ProgressNotification], Awaitable[None]]
    ) -> None:
        """Register callback for progress notifications with client context.

        Your callback receives the client ID and complete notification with all
        progress details - current amount, total expected, status messages, and
        the token identifying which operation is progressing.

        Args:
            callback: Your async function called with each ProgressNotification.
                Gets (client_id, notification) with progress_token, progress,
                total (optional), and message (optional) fields.
        """
        self._progress = callback

    async def call_progress(
        self, client_id: str, notification: ProgressNotification
    ) -> None:
        """Invoke progress callback with client context.

        Calls your progress callback if you've registered one. Logs any errors
        that occur.

        Args:
            client_id: ID of the client sending the progress notification
            notification: Progress notification to pass through to your callback.
        """
        if self._progress:
            try:
                await self._progress(client_id, notification)
            except Exception as e:
                print(f"Progress callback failed for {client_id}: {e}")

    def on_roots_changed(
        self, callback: Callable[[str, list[Root]], Awaitable[None]]
    ) -> None:
        """Register callback for when client roots change with client context.

        Your callback receives the client ID and complete list of roots that
        the client has access to.

        Args:
            callback: Your async function called with (client_id, roots) when
                a client's roots list changes.
        """
        self._roots_changed = callback

    async def call_roots_changed(self, client_id: str, roots: list[Root]) -> None:
        """Invoke roots changed callback with client context.

        Calls your roots changed callback if you've registered one. Logs any
        errors that occur.

        Args:
            client_id: ID of the client whose roots changed
            roots: Current roots list to pass through to your callback.
        """
        if self._roots_changed:
            try:
                await self._roots_changed(client_id, roots)
            except Exception as e:
                print(f"Roots changed callback failed for {client_id}: {e}")

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

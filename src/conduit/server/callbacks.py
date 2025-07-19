from typing import Awaitable, Callable

from conduit.protocol.common import CancelledNotification, ProgressNotification
from conduit.protocol.initialization import InitializedNotification
from conduit.protocol.roots import Root


class CallbackManager:
    """Manages event callbacks for client state changes."""

    def __init__(self):
        # Direct callback assignment
        self.initialized_handler: (
            Callable[[str, InitializedNotification], Awaitable[None]] | None
        ) = None
        self.progress_handler: (
            Callable[[str, ProgressNotification], Awaitable[None]] | None
        ) = None
        self.roots_changed_handler: (
            Callable[[str, list[Root]], Awaitable[None]] | None
        ) = None
        self.cancelled_handler: (
            Callable[[str, CancelledNotification], Awaitable[None]] | None
        ) = None

    async def call_initialized(
        self, client_id: str, notification: InitializedNotification
    ) -> None:
        """Invoke initialized callback with client context."""
        if self.initialized_handler:
            try:
                await self.initialized_handler(client_id, notification)
            except Exception as e:
                print(f"Initialized callback failed for {client_id}: {e}")

    async def call_progress(
        self, client_id: str, notification: ProgressNotification
    ) -> None:
        """Invoke progress callback with client context."""
        if self.progress_handler:
            try:
                await self.progress_handler(client_id, notification)
            except Exception as e:
                print(f"Progress callback failed for {client_id}: {e}")

    async def call_roots_changed(self, client_id: str, roots: list[Root]) -> None:
        """Invoke roots changed callback with client context."""
        if self.roots_changed_handler:
            try:
                await self.roots_changed_handler(client_id, roots)
            except Exception as e:
                print(f"Roots changed callback failed for {client_id}: {e}")

    async def call_cancelled(
        self, client_id: str, notification: CancelledNotification
    ) -> None:
        """Invoke cancelled callback with client context."""
        if self.cancelled_handler:
            try:
                await self.cancelled_handler(client_id, notification)
            except Exception as e:
                print(f"Cancelled callback failed for {client_id}: {e}")

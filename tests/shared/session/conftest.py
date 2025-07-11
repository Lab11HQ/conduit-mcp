import asyncio

import pytest

from tests.shared.conftest import MockTransport, TestableBaseSession


class BaseSessionTest:
    @pytest.fixture(autouse=True)
    def setup_fixtures(self):
        self.transport = MockTransport()
        self.session = TestableBaseSession(self.transport)

    @pytest.fixture(autouse=True)
    async def teardown_session(self):
        yield
        if hasattr(self, "session"):
            await self.session.stop()

    async def wait_for_sent_message(self, method: str | None = None) -> None:
        """Wait for a message to be sent."""
        for _ in range(100):  # Max 100ms wait
            if method is None:
                if self.transport.sent_messages:
                    return
            else:
                if any(
                    msg.get("method") == method for msg in self.transport.sent_messages
                ):
                    return
            await asyncio.sleep(0.001)

        if method:
            raise AssertionError(f"Message with method '{method}' never sent")
        else:
            raise AssertionError("No message was sent")

    async def yield_to_event_loop(self, seconds: float | None = None) -> None:
        """Let the event loop process pending tasks and callbacks.

        Args:
            seconds: Additional time to wait for async operations to settle.
                Defaults to 0 (single event loop tick).
        """
        if seconds is None:
            seconds = getattr(self, "_default_yield_time", 0)
        await asyncio.sleep(seconds)

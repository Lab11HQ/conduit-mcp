import asyncio

import pytest

from tests.shared.conftest import MockPeer, MockTransport, TestableBaseSession


class BaseSessionTest:
    @pytest.fixture(autouse=True)
    def setup_fixtures(self):
        self.transport = MockTransport()
        self.session = TestableBaseSession(self.transport)
        self.peer = MockPeer(self.transport)

    @pytest.fixture(autouse=True)
    async def teardown_session(self):
        yield
        if hasattr(self, "session"):
            await self.session.stop()

    async def wait_for_sent_message(self, method: str | None = None) -> None:
        """Wait for a message to be sent - simple test sync helper."""
        for _ in range(100):  # Max 100ms wait
            if method is None:
                # Wait for any message
                if self.transport.sent_messages:
                    return
            else:
                # Wait for specific method
                if any(
                    msg.get("method") == method for msg in self.transport.sent_messages
                ):
                    return
            await asyncio.sleep(0.001)

        if method:
            raise AssertionError(f"Message with method '{method}' never sent")
        else:
            raise AssertionError("No message was sent")

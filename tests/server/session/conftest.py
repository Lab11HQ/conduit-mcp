import asyncio
from typing import Any

import pytest

from conduit.protocol.base import PROTOCOL_VERSION
from conduit.protocol.initialization import (
    Implementation,
    ServerCapabilities,
)
from conduit.server.session import ServerConfig, ServerSession
from tests.shared.conftest import MockTransport


class ServerSessionTest:
    """Base test class for server session tests."""

    @pytest.fixture(autouse=True)
    def setup_fixtures(self):
        self.transport = MockTransport()
        self.config = ServerConfig(
            capabilities=ServerCapabilities(),
            info=Implementation(name="test-server", version="1.0.0"),
            instructions="Welcome to the test server!",
            protocol_version=PROTOCOL_VERSION,
        )
        self.session = ServerSession(self.transport, self.config)

    @pytest.fixture(autouse=True)
    async def teardown_session(self):
        yield
        if hasattr(self, "session"):
            await self.session.stop()

    def create_init_request(
        self,
        client_name: str = "test-client",
        client_version: str = "1.0.0",
        protocol_version: str = PROTOCOL_VERSION,
        capabilities: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a mock InitializeRequest."""
        if capabilities is None:
            capabilities = {}

        return {
            "jsonrpc": "2.0",
            "id": "test-init-1",
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "clientInfo": {
                    "name": client_name,
                    "version": client_version,
                },
                "capabilities": capabilities,
            },
        }

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
        """Let the event loop process pending tasks and callbacks."""
        if seconds is None:
            seconds = getattr(self, "_default_yield_time", 0)
        await asyncio.sleep(seconds)

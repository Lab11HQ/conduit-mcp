import asyncio
from typing import Any

import pytest

from conduit.client.session import ClientConfig, ClientSession
from conduit.protocol.base import PROTOCOL_VERSION
from conduit.protocol.initialization import ClientCapabilities, Implementation
from tests.shared.session.conftest import MockTransport


class ClientSessionTest:
    """Base test class for client session tests."""

    @pytest.fixture(autouse=True)
    def setup_fixtures(self):
        self.transport = MockTransport()
        self.config = ClientConfig(
            client_info=Implementation(name="test-client", version="1.0.0"),
            capabilities=ClientCapabilities(),
        )
        self.session = ClientSession(self.transport, self.config)

    @pytest.fixture(autouse=True)
    async def teardown_session(self):
        yield
        if hasattr(self, "session"):
            await self.session.stop()

    def create_init_response(
        self,
        request_id: str,
        server_name: str = "test-server",
        server_version: str = "1.0.0",
        protocol_version: str = PROTOCOL_VERSION,
        capabilities: dict[str, Any] | None = None,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        """Create a mock InitializeResult response."""
        if capabilities is None:
            capabilities = {}

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": protocol_version,
                "capabilities": capabilities,
                "serverInfo": {
                    "name": server_name,
                    "version": server_version,
                },
                **({"instructions": instructions} if instructions else {}),
            },
        }

    def create_init_error(
        self,
        request_id: str,
        code: int = -32603,
        message: str = "Internal error",
    ) -> dict[str, Any]:
        """Create a mock initialization error response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
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
        """Let the event loop process pending tasks and callbacks.

        Args:
            seconds: Additional time to wait for async operations to settle.
                Defaults to 0 (single event loop tick).
        """
        if seconds is None:
            seconds = getattr(self, "_default_yield_time", 0)
        await asyncio.sleep(seconds)

import asyncio

import pytest

from conduit.protocol.base import Error
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.tools import ListToolsRequest

from .conftest import BaseSessionTest


class TestSendRequest(BaseSessionTest):
    _default_yield_time = 0.01

    async def test_starts_session_before_sending(self):
        """send_request ensures session is started before sending."""
        # Arrange
        request = PingRequest()

        # Verify session isn't running initially
        assert not self.session.running

        # Act - send request (don't await, just start it)
        request_task = asyncio.create_task(self.session.send_request(request))

        # Give it a moment to call start()
        await self.yield_to_event_loop()

        # Assert - session is now running
        assert self.session.running

        # Cleanup - complete the request to avoid hanging
        await self.wait_for_sent_message("ping")
        sent_message = self.transport.sent_messages[0]
        response_payload = {"jsonrpc": "2.0", "id": sent_message["id"], "result": {}}
        self.transport.receive_message(response_payload)
        await request_task

    async def test_sends_request_and_returns_response(self):
        """Successful request/response cycle returns the peer's response."""
        # Arrange
        request = PingRequest()

        # Start session to enable message processing
        await self.session.start()

        # Act - send request in background
        request_task = asyncio.create_task(self.session.send_request(request))

        # Wait for request to be sent
        await self.wait_for_sent_message("ping")

        # Simulate peer response
        sent_message = self.transport.sent_messages[0]
        response_payload = {"jsonrpc": "2.0", "id": sent_message["id"], "result": {}}
        self.transport.receive_message(response_payload)

        # Wait for completion
        result = await request_task

        # Assert
        assert isinstance(result, EmptyResult)

    async def test_raises_runtime_error_for_non_ping_when_not_initialized(self):
        """Non-ping requests raise RuntimeError when session not initialized."""
        # Arrange - create a non-ping request
        request = ListToolsRequest()

        # Make session uninitialized
        self.session._is_initialized = False

        # Act & Assert
        with pytest.raises(RuntimeError, match="Session must be initialized"):
            await self.session.send_request(request)

    async def test_allows_ping_requests_when_not_initialized(self):
        """Ping requests work even when session not initialized."""
        # Arrange
        request = PingRequest()

        # Make session uninitialized
        self.session._is_initialized = False

        # Act - should not raise
        request_task = asyncio.create_task(self.session.send_request(request))

        # Complete the request
        await self.wait_for_sent_message("ping")
        sent_message = self.transport.sent_messages[0]
        response_payload = {"jsonrpc": "2.0", "id": sent_message["id"], "result": {}}
        self.transport.receive_message(response_payload)

        result = await request_task
        assert isinstance(result, EmptyResult)

    async def test_returns_error_response_from_peer(self):
        """Error responses from peer are returned as Error objects."""
        # Arrange
        request = PingRequest()

        # Act - send request in background
        request_task = asyncio.create_task(self.session.send_request(request))

        # Wait for request to be sent
        await self.wait_for_sent_message("ping")

        # Simulate peer error response
        sent_message = self.transport.sent_messages[0]
        error_response = {
            "jsonrpc": "2.0",
            "id": sent_message["id"],
            "error": {
                "code": -32601,
                "message": "Method not found",
                "data": {"details": "Unknown method"},
            },
        }
        self.transport.receive_message(error_response)

        # Wait for completion
        result = await request_task

        # Assert - error response returned as Error object
        assert isinstance(result, Error)
        assert result.code == -32601
        assert result.message == "Method not found"
        assert result.data == {"details": "Unknown method"}

    async def test_timeout_raises_error_and_sends_cancellation(self):
        """Request timeout raises TimeoutError and sends cancellation notification."""
        # Arrange
        request = PingRequest()

        # Act - start request and wait for it to be sent
        request_task = asyncio.create_task(
            self.session.send_request(request, timeout=0.05)
        )
        await self.wait_for_sent_message("ping")

        # Assert - timeout should raise
        with pytest.raises(TimeoutError, match="timed out after 0.05s"):
            await request_task

        # Assert - cancellation notification was sent
        await self.wait_for_sent_message("notifications/cancelled")

        # Assert - two messages total
        assert len(self.transport.sent_messages) == 2

        # Assert - cancellation details
        cancellation_msg = next(
            msg
            for msg in self.transport.sent_messages
            if msg.get("method") == "notifications/cancelled"
        )
        assert "timed out" in cancellation_msg["params"]["reason"]

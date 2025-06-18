import asyncio

import pytest

from conduit.protocol.common import (
    EmptyResult,
    PingRequest,
)

from .conftest import BaseSessionTest


class TestClientSessionRequestResponse(BaseSessionTest):
    async def test_response_with_unknown_id_doesnt_hang(self):
        await self.session._start()

        # Queue a response for a request that was never sent
        self.server.send_message(
            payload={"jsonrpc": "2.0", "id": 999, "result": {"data": "orphaned"}}
        )

        # Queue a second message to prove the loop is still processing
        self.server.send_message(
            payload={"jsonrpc": "2.0", "id": 1000, "result": {"data": "second"}}
        )

        # The loop should still be running (not hung)
        assert self.session._running is True
        assert not self.session._message_loop_task.done()

        await self.session.stop()

    async def test_malformed_response_doesnt_crash_message_loop(self):
        """Malformed response should not crash the message loop."""
        await self.session._start()

        # Queue a response missing both result and error
        self.server.send_message(payload={"jsonrpc": "2.0", "id": 123})

        # Loop should still be running
        assert self.session._running is True

        await self.session.stop()

    async def test_concurrent_requests_out_of_order_responses(self):
        """Test that out-of-order responses correlate correctly."""
        self.session._initialized = True

        # Send both requests first
        request1 = PingRequest()
        request2 = PingRequest()

        # Start both requests (don't await yet)
        task1 = asyncio.create_task(self.session.send_request(request1))
        task2 = asyncio.create_task(self.session.send_request(request2))

        # Now queue responses in reverse order
        self.server.send_message(
            payload={"jsonrpc": "2.0", "id": 1, "result": {"result": "second"}}
        )
        self.server.send_message(
            payload={"jsonrpc": "2.0", "id": 0, "result": {"result": "first"}}
        )

        # Both should complete correctly despite reverse order
        result1 = await task1
        result2 = await task2

        assert result1 == EmptyResult()
        assert result2 == EmptyResult()

        await self.session.stop()

    async def test_request_timeout_send_cancellation_and_raises(self):
        self.session._initialized = True

        request = PingRequest()
        with pytest.raises(TimeoutError):
            await self.session.send_request(request, timeout=1e-9)

        assert self.session._pending_requests == {}

        cancel_message = self.transport.client_sent_messages[-1].payload
        assert cancel_message["method"] == "notifications/cancelled"

        await self.session.stop()

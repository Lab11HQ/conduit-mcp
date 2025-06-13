import asyncio

import pytest

from conduit.protocol.base import INTERNAL_ERROR
from conduit.protocol.common import (
    CancelledNotification,
    PingRequest,
)
from conduit.protocol.content import TextContent
from conduit.protocol.initialization import RootsCapability
from conduit.protocol.logging import LoggingMessageNotification
from conduit.protocol.roots import Root
from conduit.protocol.sampling import (
    CreateMessageRequest,
    CreateMessageResult,
    SamplingMessage,
)
from conduit.shared.exceptions import MCPError

from .conftest import BaseSessionTest


class TestClientSessionRequestResponse(BaseSessionTest):
    async def test_response_with_unknown_id_doesnt_hang(self):
        await self.session._start()

        # Queue a response for a request that was never sent
        self.transport.queue_response(request_id=999, result={"data": "orphaned"})

        # Queue a second message to prove the loop is still processing
        self.transport.queue_message({"test": "marker"})

        # The loop should still be running (not hung)
        assert self.session._running is True
        assert not self.session._task.done()

        await self.session.stop()

    async def test_malformed_response_doesnt_crash_message_loop(self):
        """Malformed response should not crash the message loop."""
        await self.session._start()

        # Queue a response missing both result and error
        self.transport.queue_message(
            {
                "jsonrpc": "2.0",
                "id": 123,
                # Missing "result" or "error"
            }
        )

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
        self.transport.queue_response(1, {"result": "second"})
        self.transport.queue_response(0, {"result": "first"})

        # Both should complete correctly despite reverse order
        result1, _ = await task1
        result2, _ = await task2

        assert result1 == {"result": "first"}
        assert result2 == {"result": "second"}

        await self.session.stop()

    async def test_request_timeout_send_cancellation_and_raises(self):
        self.session._initialized = True

        request = PingRequest()
        with pytest.raises(TimeoutError):
            await self.session.send_request(request, timeout=1e-9)

        assert self.session._pending_requests == {}

        cancel_message = self.transport.sent_messages[-1].payload
        assert cancel_message["method"] == "notifications/cancelled"

        await self.session.stop()

    async def test_send_notification_sends_message_to_transport(self):
        notification = CancelledNotification(request_id=42, reason="test")
        await self.session.send_notification(notification)

        sent_message = self.transport.sent_messages[-1].payload
        assert sent_message["method"] == "notifications/cancelled"
        assert sent_message["params"]["requestId"] == 42
        assert sent_message["params"]["reason"] == "test"
        assert "id" not in sent_message  # Notifications don't have IDs

        await self.session.stop()

    async def test_send_notification_propagates_transport_errors(self):
        # Make transport.send raise
        self.transport.closed = True

        notification = CancelledNotification(request_id=42, reason="test")

        with pytest.raises(ConnectionError, match="Transport closed"):
            await self.session.send_notification(notification)

        await self.session.stop()

    async def test_notification_handler_parses_and_queues_notification(self):
        self.session._initialized = True

        # Send a logging notification
        notification_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {"level": "info", "data": {"message": "test log"}},
        }
        self.transport.queue_message(notification_payload)

        await self.session._start()

        # Should be queued for consumption
        notification = await self.session.notifications.get()
        assert isinstance(notification, LoggingMessageNotification)
        assert notification.level == "info"

        await self.session.stop()

    async def test_notification_handler_does_not_crash_on_unknown_method(self):
        self.session._initialized = True

        bad_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/unknown",
            "params": {},
        }
        good_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {"level": "info", "data": {"message": "test log"}},
        }
        self.transport.queue_message(bad_notification)

        await self.session._start()

        # Should not break the session - notification queue should be empty
        assert self.session.notifications.empty()
        assert self.session._running is True

        self.transport.queue_message(good_notification)
        notification = await self.session.notifications.get()
        assert isinstance(notification, LoggingMessageNotification)
        assert notification.level == "info"

        await self.session.stop()

    async def test_response_handler_resolves_pending_request_with_result(self):
        self.session._initialized = True

        # Set up a pending request manually
        request_id = 42
        future = asyncio.Future()
        self.session._pending_requests[request_id] = future

        # Send success response
        response_payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"data": "test"},
        }
        self.transport.queue_message(response_payload, metadata={"test": "meta"})

        await self.session._start()

        # Future should be resolved with result and metadata
        result, metadata = await future
        assert result == {"data": "test"}
        assert metadata == {"test": "meta"}

        await self.session.stop()

    async def test_response_handler_resolves_pending_request_with_error(self):
        self.session._initialized = True

        # Set up pending request
        request_id = 42
        future = asyncio.Future()
        self.session._pending_requests[request_id] = future

        # Send error response
        error_payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -1, "message": "test error"},
        }
        self.transport.queue_message(error_payload)

        await self.session._start()

        # Future should be resolved with MCPError
        with pytest.raises(MCPError) as exc_info:
            await future
        assert exc_info.value.error.message == "test error"

        await self.session.stop()

    async def test_response_handler_buffers_orphaned_response(self):
        self.session._initialized = True

        # Send response with no matching pending request
        orphaned_payload = {"jsonrpc": "2.0", "id": 999, "result": {"orphaned": True}}
        self.transport.queue_message(orphaned_payload, metadata={"meta": "data"})

        await self.session._start()

        # Wait for background message loop to process the queued message
        await asyncio.sleep(0.001)

        # Should be buffered, not cause errors
        assert 999 in self.session._buffered_responses
        buffered_payload, buffered_metadata = self.session._buffered_responses[999]
        assert buffered_payload["result"] == {"orphaned": True}
        assert buffered_metadata == {"meta": "data"}

        await self.session.stop()

    async def test_request_handler_responds_to_ping(self):
        self.session._initialized = True

        # Send a ping request
        ping_payload = {"jsonrpc": "2.0", "method": "ping", "id": 42}
        self.transport.queue_message(ping_payload)

        await self.session._start()

        # Wait for message processing
        await asyncio.sleep(0.001)

        # Should have sent back a response
        response_message = self.transport.sent_messages[-1].payload
        assert response_message["jsonrpc"] == "2.0"
        assert response_message["id"] == 42
        assert response_message["result"] == {}

        await self.session.stop()

    async def test_request_handler_rejects_list_roots_without_capability(self):
        self.session._initialized = True
        self.session.capabilities.roots = None
        # Note: session starts with no roots capability by default

        list_roots_payload = {"jsonrpc": "2.0", "method": "roots/list", "id": 42}
        self.transport.queue_message(list_roots_payload)

        await self.session._start()
        await asyncio.sleep(0.001)

        # Should send error response
        response_message = self.transport.sent_messages[-1].payload
        assert response_message["jsonrpc"] == "2.0"
        assert response_message["id"] == 42
        assert "error" in response_message
        assert (
            "does not support roots capability" in response_message["error"]["message"]
        )

        await self.session.stop()

    async def test_request_handler_returns_configured_roots(self):
        # Set up session with roots capability and some roots
        roots = [Root(uri="file:///test", name="test")]
        self.session.capabilities.roots = RootsCapability()
        self.session.roots = roots
        self.session._initialized = True

        list_roots_payload = {"jsonrpc": "2.0", "method": "roots/list", "id": 42}
        self.transport.queue_message(list_roots_payload)

        await self.session._start()
        await asyncio.sleep(0.001)

        # Should return the configured roots
        response_message = self.transport.sent_messages[-1].payload
        assert response_message["id"] == 42
        assert "result" in response_message
        assert response_message["result"]["roots"] == [
            root.model_dump(mode="json") for root in roots
        ]

        await self.session.stop()

    async def test_request_handler_rejects_create_message_without_capability(self):
        self.session._initialized = True
        self.session.capabilities.sampling = False

        sampling_message = SamplingMessage(
            role="user",
            content=TextContent(text="Hello, world!"),
        )

        create_message_payload = {
            "jsonrpc": "2.0",
            "method": "sampling/createMessage",
            "id": 42,
            "params": {
                "messages": [sampling_message.model_dump(mode="json")],
                "maxTokens": 100,
            },
        }
        self.transport.queue_message(create_message_payload)

        await self.session._start()
        await asyncio.sleep(0.001)

        # Should send error response
        response_message = self.transport.sent_messages[-1].payload
        assert response_message["jsonrpc"] == "2.0"
        assert response_message["id"] == 42
        assert "error" in response_message
        assert (
            "does not support sampling capability"
            in response_message["error"]["message"]
        )

        await self.session.stop()

    async def test_request_handler_rejects_create_message_without_handler(self):
        # Enable capability but don't provide handler
        self.session.capabilities.sampling = True
        self.session._initialized = True

        sampling_message = SamplingMessage(
            role="user",
            content=TextContent(text="Hello, world!"),
        )

        create_message_payload = {
            "jsonrpc": "2.0",
            "method": "sampling/createMessage",
            "id": 42,
            "params": {
                "messages": [sampling_message.model_dump(mode="json")],
                "maxTokens": 100,
            },
        }
        self.transport.queue_message(create_message_payload)

        await self.session._start()
        await asyncio.sleep(0.001)

        # Should send error response
        response_message = self.transport.sent_messages[-1].payload
        assert "error" in response_message
        assert (
            "Sampling capability enabled but internal handler not configured"
            in response_message["error"]["message"]
        )

        await self.session.stop()

    async def test_request_handler_calls_create_message_handler(self):
        self.session.capabilities.sampling = True

        async def mock_handler(request: CreateMessageRequest) -> CreateMessageResult:
            return CreateMessageResult(
                role="assistant",
                content=TextContent(text="test response"),
                model="test-model",
                stop_reason="endTurn",
            )

        self.session.create_message_handler = mock_handler
        self.session._initialized = True

        sampling_message = SamplingMessage(
            role="user",
            content=TextContent(text="Hello, world!"),
        )

        create_message_payload = {
            "jsonrpc": "2.0",
            "method": "sampling/createMessage",
            "id": 42,
            "params": {
                "messages": [sampling_message.model_dump(mode="json")],
                "maxTokens": 100,
            },
        }
        self.transport.queue_message(create_message_payload)

        await self.session._start()
        await asyncio.sleep(0.001)

        # Should successfully call handler and return result
        response_message = self.transport.sent_messages[-1].payload
        assert response_message["jsonrpc"] == "2.0"
        assert response_message["id"] == 42
        assert "result" in response_message
        assert response_message["result"]["model"] == "test-model"
        assert response_message["result"]["content"]["text"] == "test response"

        await self.session.stop()

    async def test_request_handler_rejects_malformed_id(self):
        self.session._initialized = True

        # Test different types of malformed IDs
        test_cases = [
            {"jsonrpc": "2.0", "method": "ping"},  # Missing ID
            {"jsonrpc": "2.0", "method": "ping", "id": None},  # Null ID
            {"jsonrpc": "2.0", "method": "ping", "id": {"not": "valid"}},  # Object ID
            {"jsonrpc": "2.0", "method": "ping", "id": [1, 2, 3]},  # Array ID
        ]

        for malformed_payload in test_cases:
            self.transport.queue_message(malformed_payload)

        await self.session._start()
        await asyncio.sleep(0.001)

        # Should have attempted to send error responses, but may have failed due to bad
        # IDs. The key thing is the session should still be running
        assert self.session._running is True

        # Test that valid requests still work after malformed ones
        valid_payload = {"jsonrpc": "2.0", "method": "ping", "id": 42}
        self.transport.queue_message(valid_payload)
        await asyncio.sleep(0.001)

        # Should have at least one successful response for the valid request
        valid_responses = [
            msg for msg in self.transport.sent_messages if msg.payload.get("id") == 42
        ]
        assert len(valid_responses) == 1

        await self.session.stop()

    async def test_create_message_handler_exception_returns_internal_error(self):
        self.session.capabilities.sampling = True
        self.session._initialized = True

        async def broken_handler(request: CreateMessageRequest) -> CreateMessageResult:
            raise ValueError("Something went wrong in user code!")

        self.session.create_message_handler = broken_handler

        sampling_message = SamplingMessage(
            role="user",
            content=TextContent(text="Hello, world!"),
        )

        create_message_payload = {
            "jsonrpc": "2.0",
            "method": "sampling/createMessage",
            "id": 42,
            "params": {
                "messages": [sampling_message.model_dump(mode="json")],
                "maxTokens": 100,
            },
        }
        self.transport.queue_message(create_message_payload)

        await self.session._start()
        await asyncio.sleep(0.001)

        # Should get back an INTERNAL_ERROR response, not crash
        response_message = self.transport.sent_messages[-1].payload
        assert response_message["jsonrpc"] == "2.0"
        assert response_message["id"] == 42
        assert "error" in response_message
        assert response_message["error"]["code"] == INTERNAL_ERROR
        assert (
            "Something went wrong in user code!" in response_message["error"]["message"]
        )

        # Session should still be running
        assert self.session._running is True

        await self.session.stop()

    async def test_slow_create_message_handler_does_not_block_loop(self):
        self.session.capabilities.sampling = True
        self.session._initialized = True

        # Use events to control timing precisely
        handler_started = asyncio.Event()
        handler_can_continue = asyncio.Event()

        async def controlled_slow_handler(
            request: CreateMessageRequest,
        ) -> CreateMessageResult:
            handler_started.set()  # Signal that handler has started
            await (
                handler_can_continue.wait()
            )  # Wait for test to give permission to continue
            return CreateMessageResult(
                role="assistant",
                content=TextContent(text="slow response"),
                model="test-model",
                stop_reason="endTurn",
            )

        self.session.create_message_handler = controlled_slow_handler

        # Send slow request then fast request
        self.transport.queue_message(
            {
                "jsonrpc": "2.0",
                "method": "sampling/createMessage",
                "id": 1,
                "params": {
                    "messages": [
                        SamplingMessage(
                            role="user", content=TextContent(text="test")
                        ).model_dump(mode="json")
                    ],
                    "maxTokens": 100,
                },
            }
        )
        self.transport.queue_message({"jsonrpc": "2.0", "method": "ping", "id": 2})

        await self.session._start()

        # Wait for slow handler to start
        await handler_started.wait()

        # At this point, slow handler is running but blocked
        # The ping should still get processed
        await asyncio.sleep(0.01)  # Give message loop a chance to process ping

        ping_responses = [
            msg for msg in self.transport.sent_messages if msg.payload.get("id") == 2
        ]
        assert len(ping_responses) == 1, (
            "Ping should be processed while slow handler is blocked"
        )

        # Now let the slow handler finish
        handler_can_continue.set()
        await asyncio.sleep(0.01)
        assert len(self.transport.sent_messages) == 2, (
            f"Expected 2 responses, got {len(self.transport.sent_messages)}"
        )

        ping_responses = [
            msg for msg in self.transport.sent_messages if msg.payload.get("id") == 2
        ]
        slow_responses = [
            msg for msg in self.transport.sent_messages if msg.payload.get("id") == 1
        ]

        assert len(ping_responses) == 1, "Should have exactly one ping response"
        assert len(slow_responses) == 1, "Should have exactly one slow handler response"

        # Verify the ping response is correct
        ping_response = ping_responses[0].payload
        assert ping_response["result"] == {}

        # Verify the slow response is correct
        slow_response = slow_responses[0].payload
        assert "result" in slow_response
        assert slow_response["result"]["model"] == "test-model"

    # async def test_request_timeout_does_not_affect_subsequent_requests(self):
    #     self.session._initialized = True

    #     # First request will timeout
    #     request1 = PingRequest()
    #     with pytest.raises(TimeoutError):
    #         await self.session.send_request(request1, timeout=1e-9)

    #     # Second request should work fine
    #     request2 = PingRequest()
    #     self.transport.queue_response(request_id=1, result={})

    #     result, _ = await self.session.send_request(request2)

    #     assert result == {}
    #     assert self.session._running is True
    #     assert self.session._pending_requests == {}
    #     assert len(self.transport.sent_messages) == 3  # 1 ping, 1 cancel, 1 response

    #     await self.session.stop()

import asyncio
from unittest.mock import AsyncMock

from tests.shared.session.conftest import BaseSessionTest


class TestMessageHandler(BaseSessionTest):
    _default_yield_time = 0.01

    """Test the _handle_message method's routing and error handling."""

    async def test_routes_response_to_response_handler(self):
        """Valid responses are routed to _handle_response."""
        # Arrange
        self.session._handle_response = AsyncMock()
        response_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "result": {"status": "ok"},
        }

        # Act
        await self.session._handle_message(response_payload)

        # Assert
        self.session._handle_response.assert_called_once_with(response_payload)

    async def test_routes_notification_to_notification_handler(self):
        """Valid notifications are routed to _handle_notification."""
        # Arrange
        self.session._handle_notification = AsyncMock()
        notification_payload = {"jsonrpc": "2.0", "method": "notifications/test"}

        # Act
        await self.session._handle_message(notification_payload)

        # Assert
        self.session._handle_notification.assert_called_once_with(notification_payload)

    async def test_routes_request_to_request_handler(self):
        """Valid requests spawn tasks and are tracked."""
        # Arrange - create controlled async handler
        handler_started = asyncio.Event()
        handler_can_finish = asyncio.Event()

        async def controlled_request_handler(payload):
            handler_started.set()
            await handler_can_finish.wait()  # Wait for permission to finish

        self.session._handle_request = controlled_request_handler
        request_payload = {"jsonrpc": "2.0", "id": "req-456", "method": "test/method"}

        # Act
        await self.session._handle_message(request_payload)

        # Wait for handler to start but not finish
        await asyncio.wait_for(handler_started.wait(), timeout=0.1)

        # Assert - task should exist while handler is running
        assert "req-456" in self.session._in_flight_requests
        task = self.session._in_flight_requests["req-456"]
        assert isinstance(task, asyncio.Task)
        assert task.get_name() == "handle_request_req-456"
        assert not task.done()

        # Cleanup - let handler finish
        handler_can_finish.set()
        await asyncio.wait_for(task, timeout=0.1)

        # Task should be cleaned up after completion
        assert "req-456" not in self.session._in_flight_requests

    async def test_requests_dont_block_other_message_processing(self):
        """Request handling runs concurrently and doesn't block other messages."""
        # Arrange - controlled handlers
        request_started = asyncio.Event()
        request_can_finish = asyncio.Event()
        notification_handled = asyncio.Event()

        async def slow_request_handler(payload):
            request_started.set()
            await request_can_finish.wait()

        async def fast_notification_handler(payload):
            notification_handled.set()

        self.session._handle_request = slow_request_handler
        self.session._handle_notification = fast_notification_handler

        # Act - send request first, then notification
        request_payload = {"jsonrpc": "2.0", "id": "slow-req", "method": "slow/method"}
        notification_payload = {"jsonrpc": "2.0", "method": "fast/notification"}

        await self.session._handle_message(request_payload)
        await self.session._handle_message(notification_payload)

        # Assert - notification completes while request is still running
        await asyncio.wait_for(request_started.wait(), timeout=0.1)
        await asyncio.wait_for(notification_handled.wait(), timeout=0.1)

        # Request should still be running
        assert "slow-req" in self.session._in_flight_requests
        task = self.session._in_flight_requests["slow-req"]
        assert not task.done()

        # Cleanup - let request finish
        request_can_finish.set()
        await asyncio.wait_for(task, timeout=0.1)
        assert "slow-req" not in self.session._in_flight_requests

    async def test_processes_batch_messages(self):
        """Batch messages are processed individually."""
        # Arrange
        self.session._handle_response = AsyncMock()
        self.session._handle_notification = AsyncMock()

        batch_payload = [
            {"jsonrpc": "2.0", "id": "1", "result": {"status": "ok"}},
            {"jsonrpc": "2.0", "method": "test/notification"},
        ]

        # Act
        await self.session._handle_message(batch_payload)

        # Assert
        self.session._handle_response.assert_called_once()
        self.session._handle_notification.assert_called_once()

    async def test_notifications_dont_block_other_message_processing(self):
        """Notification handling runs concurrently and doesn't block other messages."""
        # Arrange - controlled handlers
        notification_started = asyncio.Event()
        notification_can_finish = asyncio.Event()
        response_handled = asyncio.Event()

        async def slow_notification_handler(payload):
            notification_started.set()
            await notification_can_finish.wait()

        async def fast_response_handler(payload):
            response_handled.set()

        self.session._handle_notification = slow_notification_handler
        self.session._handle_response = fast_response_handler

        # Act - send notification first, then response
        notification_payload = {"jsonrpc": "2.0", "method": "slow/notification"}
        response_payload = {"jsonrpc": "2.0", "id": "fast-response", "result": {}}

        await self.session._handle_message(notification_payload)
        await self.session._handle_message(response_payload)

        # Assert - response completes while notification is still running
        await asyncio.wait_for(notification_started.wait(), timeout=0.1)
        await asyncio.wait_for(response_handled.wait(), timeout=0.1)

        assert notification_started.is_set()  # Notification did start
        assert response_handled.is_set()  # Response was handled
        assert not notification_can_finish.is_set()  # Notification still pending

        # Cleanup - let notification finish
        notification_can_finish.set()
        await self.yield_to_event_loop()

        assert notification_can_finish.is_set()  # Notification completed

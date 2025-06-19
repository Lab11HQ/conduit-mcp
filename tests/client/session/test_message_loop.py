import asyncio
from unittest.mock import AsyncMock

import pytest

from .conftest import BaseSessionTest


class TestMessageLoop(BaseSessionTest):
    async def test_message_loop_calls_handler_for_each_message(self):
        """Happy path: message loop processes messages by calling the handler."""
        # Arrange: mock the handler method
        handler_calls = []

        async def mock_handler(payload):
            handler_calls.append(payload)

        self.session._handle_message = mock_handler

        # Act: start the session (which starts the message loop)
        await self.session._start()

        # Act: send a few messages from the server
        self.server.send_message({"jsonrpc": "2.0", "method": "notifications/test1"})
        self.server.send_message({"jsonrpc": "2.0", "method": "notifications/test2"})
        self.server.send_message({"jsonrpc": "2.0", "method": "notifications/test3"})

        await asyncio.sleep(0.01)

        # Act: stop the session
        await self.session.stop()

        # Assert: verify handler was called for each message
        assert len(handler_calls) == 3
        assert handler_calls == [
            {"jsonrpc": "2.0", "method": "notifications/test1"},
            {"jsonrpc": "2.0", "method": "notifications/test2"},
            {"jsonrpc": "2.0", "method": "notifications/test3"},
        ]

    async def test_handler_error_doesnt_stop_loop(self):
        """Error isolation: handler crashes don't kill the message loop."""
        # Arrange: mock the handler method
        handler_calls = []

        async def mock_handler(payload):
            handler_calls.append(payload)
            # Crash on the second message
            if len(handler_calls) == 2:
                raise ValueError("Handler crashed!")

        self.session._handle_message = mock_handler

        # Act: start the session
        await self.session._start()

        # Act: send messages - second one will crash the handler
        self.server.send_message({"jsonrpc": "2.0", "method": "notifications/test1"})
        self.server.send_message({"jsonrpc": "2.0", "method": "notifications/crash"})
        self.server.send_message({"jsonrpc": "2.0", "method": "notifications/test3"})

        # Act: give the loop time to process
        await asyncio.sleep(0.01)

        # Act: stop the session
        await self.session.stop()

        # Assert: verify all messages were attempted (including the one that crashed)
        assert len(handler_calls) == 3
        assert handler_calls == [
            {"jsonrpc": "2.0", "method": "notifications/test1"},
            {"jsonrpc": "2.0", "method": "notifications/crash"},
            {"jsonrpc": "2.0", "method": "notifications/test3"},
        ]

    async def test_transport_error_stops_loop_and_cleans_up(self):
        """Transport errors stop the loop and trigger proper cleanup."""
        # Arrange: mock the handler method
        handler_calls = []

        async def mock_handler(payload):
            handler_calls.append(payload)

        self.session._handle_message = mock_handler

        # Act: start the session
        await self.session._start()

        # Act: send a message to confirm loop is running
        msg = {"jsonrpc": "2.0", "method": "notifications/test1"}
        self.server.send_message(msg)
        await asyncio.sleep(0.01)  # Let it process

        # Act: simulate transport failure by closing it
        self.transport.simulate_error()

        # Act: give the loop time to detect the failure and shut down
        await asyncio.sleep(0.01)

        # Assert: verify the loop detected the failure and cleaned up
        assert not self.session._running
        assert (
            self.session._message_loop_task is None
            or self.session._message_loop_task.done()
        )

        # Assert: verify we processed the message before the transport failed
        assert len(handler_calls) == 1
        assert handler_calls[0] == msg

    async def test_loop_respects_running_flag_on_stop(self):
        """Loop exits cleanly when stop() is called, even with queued messages."""
        # Arrange: mock the handler method
        handler_calls = []

        async def mock_handler(payload):
            handler_calls.append(payload)

        self.session._handle_message = mock_handler

        # Act: start the session
        await self.session._start()

        # Act: send one message and let it process
        self.server.send_message(
            {"jsonrpc": "2.0", "method": "notifications/processed"}
        )
        await asyncio.sleep(0.01)

        # Act: stop the session immediately
        await self.session.stop()

        # Act: queue up more messages after the session is stopped
        self.server.send_message({"jsonrpc": "2.0", "method": "notifications/queued1"})
        self.server.send_message({"jsonrpc": "2.0", "method": "notifications/queued2"})

        # Assert: verify only the first message was processed
        assert len(handler_calls) == 1
        assert handler_calls[0] == {
            "jsonrpc": "2.0",
            "method": "notifications/processed",
        }

        # Assert: verify session is properly stopped
        assert not self.session._running
        assert self.session._message_loop_task is None


class TestMessageHandler(BaseSessionTest):
    async def test_routes_response_to_handler(self, monkeypatch):
        # Arrange
        response_payload = {
            "jsonrpc": "2.0",
            "id": "42",
            "result": {"success": "yes"},
        }

        # Act
        mock_handle_response = AsyncMock()
        monkeypatch.setattr(self.session, "_handle_response", mock_handle_response)

        await self.session._handle_message(response_payload)

        # Assert
        mock_handle_response.assert_awaited_once_with(response_payload)

    async def test_routes_notification_to_handler(self, monkeypatch):
        # Arrange
        notification_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {"progressToken": "task-123", "value": 0.75},
        }

        # Act
        mock_handle_notification = AsyncMock()
        monkeypatch.setattr(
            self.session, "_handle_notification", mock_handle_notification
        )

        await self.session._handle_message(notification_payload)

        # Assert
        mock_handle_notification.assert_awaited_once_with(notification_payload)

    async def test_routes_request_to_handler(self, monkeypatch):
        # Arrange
        request_payload = {"jsonrpc": "2.0", "method": "ping", "id": "123"}

        mock_handle_request = AsyncMock()
        monkeypatch.setattr(self.session, "_handle_request", mock_handle_request)

        # Act
        await self.session._handle_message(request_payload)

        # Give the task a moment to run
        await asyncio.sleep(0)

        # Assert
        mock_handle_request.assert_awaited_once_with(request_payload)

    async def test_requests_dont_block_message_processing(self, monkeypatch):
        # Arrange
        request_handler_started = asyncio.Event()
        request_handler_can_finish = asyncio.Event()
        request_handler_finished = asyncio.Event()
        notification_handler_called = asyncio.Event()

        async def slow_request_handler(*args):
            request_handler_started.set()
            await request_handler_can_finish.wait()  # Wait for permission to finish
            request_handler_finished.set()

        async def notification_handler(*args):
            notification_handler_called.set()

        monkeypatch.setattr(self.session, "_handle_request", slow_request_handler)
        monkeypatch.setattr(self.session, "_handle_notification", notification_handler)

        # Act
        request_msg = {"jsonrpc": "2.0", "method": "long/running/request", "id": "1"}
        notification_msg = {"jsonrpc": "2.0", "method": "important/notification"}

        await self.session._handle_message(request_msg)
        await self.session._handle_message(notification_msg)

        # Assert - notification completes while request is still pending
        await asyncio.wait_for(request_handler_started.wait(), timeout=0.5)
        await asyncio.wait_for(notification_handler_called.wait(), timeout=0.5)

        assert request_handler_started.is_set()  # Request did start
        assert notification_handler_called.is_set()  # Notification was handled
        assert not request_handler_finished.is_set()  # Request still pending

        # Clean up - let request finish
        request_handler_can_finish.set()
        await asyncio.wait_for(request_handler_finished.wait(), timeout=0.5)

        assert request_handler_finished.is_set()  # Request completed

    async def test_raises_on_unknown_message_type(self):
        # Arrange
        # Missing both "method" (request/notification) and "result"/"error" (response)
        malformed_payload = {
            "jsonrpc": "2.0",
            "id": "123",
            "not-result-error-or-method": "BOOM",
        }

        # Act & Assert
        with pytest.raises(ValueError, match="Unknown message type"):
            await self.session._handle_message(malformed_payload)

import asyncio
from unittest.mock import AsyncMock

import pytest

from conduit.protocol.base import INTERNAL_ERROR, METHOD_NOT_FOUND
from conduit.protocol.common import PingRequest, ProgressNotification
from conduit.protocol.content import TextContent
from conduit.protocol.initialization import RootsCapability
from conduit.protocol.roots import Root
from conduit.protocol.sampling import CreateMessageRequest, CreateMessageResult
from conduit.shared.exceptions import UnknownNotificationError
from conduit.transport.base import TransportMessage

from .conftest import BaseSessionTest


class TestMessageLoop(BaseSessionTest):
    async def test_message_loop_calls_handler_for_each_message(self):
        """Happy path: message loop processes messages by calling the handler."""
        # Arrange: mock the handler method
        handler_calls = []

        async def mock_handler(message):
            handler_calls.append(message.payload)

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

        async def mock_handler(message):
            handler_calls.append(message.payload)
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

        async def mock_handler(message):
            handler_calls.append(message.payload)

        self.session._handle_message = mock_handler

        # Act: start the session
        await self.session._start()

        # Act: send a message to confirm loop is running
        self.server.send_message({"jsonrpc": "2.0", "method": "notifications/test1"})
        await asyncio.sleep(0.01)  # Let it process

        # Act: simulate transport failure by closing it
        await self.transport.close()

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
        assert handler_calls[0] == {"jsonrpc": "2.0", "method": "notifications/test1"}

    async def test_loop_respects_running_flag_on_stop(self):
        """Loop exits cleanly when stop() is called, even with queued messages."""
        # Arrange: mock the handler method
        handler_calls = []

        async def mock_handler(message):
            handler_calls.append(message.payload)

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
            "id": 42,
            "result": {"status": "success", "data": "test_data"},
        }
        transport_metadata = {"transport": "test", "timestamp": "2025-01-01"}

        # Act
        mock_handle_response = AsyncMock()
        monkeypatch.setattr(self.session, "_handle_response", mock_handle_response)

        message = TransportMessage(
            payload=response_payload, metadata=transport_metadata
        )
        await self.session._handle_message(message)

        # Assert
        mock_handle_response.assert_awaited_once_with(
            response_payload, transport_metadata
        )

    async def test_routes_notification_to_handler(self, monkeypatch):
        # Arrange
        notification_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {"progressToken": "task-123", "value": 0.75},
        }
        transport_metadata = {"source": "server", "timestamp": "2025-01-01"}

        # Act
        mock_handle_notification = AsyncMock()
        monkeypatch.setattr(
            self.session, "_handle_notification", mock_handle_notification
        )

        message = TransportMessage(
            payload=notification_payload, metadata=transport_metadata
        )
        await self.session._handle_message(message)

        # Assert
        mock_handle_notification.assert_awaited_once_with(
            notification_payload, transport_metadata
        )

    async def test_routes_request_to_async_task(self, monkeypatch):
        # Arrange
        request_payload = {"jsonrpc": "2.0", "method": "ping", "id": 123}
        transport_metadata = {"auth": "token"}

        mock_handle_request = AsyncMock()
        monkeypatch.setattr(self.session, "_handle_request", mock_handle_request)

        # Act
        message = TransportMessage(payload=request_payload, metadata=transport_metadata)
        await self.session._handle_message(message)

        # Give the task a moment to run
        await asyncio.sleep(0)

        # Assert
        mock_handle_request.assert_awaited_once_with(
            request_payload, transport_metadata
        )

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
        request_msg = TransportMessage(
            payload={"jsonrpc": "2.0", "method": "long/running/request", "id": 1}
        )
        notification_msg = TransportMessage(
            payload={"jsonrpc": "2.0", "method": "important/notification"}
        )

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
            "id": 123,
            "unknown_field": "data",
        }

        # Act & Assert
        message = TransportMessage(payload=malformed_payload)
        with pytest.raises(ValueError, match="Unknown message type"):
            await self.session._handle_message(message)


class TestResponseHandler(BaseSessionTest):
    async def test_resolves_successful_response_future(self):
        # Arrange
        request_id = 42
        expected_payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"data": "success"},
        }
        expected_metadata = {"transport": "test"}

        # Create and store a pending future
        future = asyncio.Future()
        self.session._pending_requests[request_id] = future

        # Act
        await self.session._handle_response(expected_payload, expected_metadata)

        # Assert
        assert future.done()
        payload, metadata = future.result()
        assert payload == expected_payload
        assert metadata == expected_metadata

    async def test_resolves_error_response_future(self):
        # Arrange
        request_id = 123
        expected_payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Method not found"},
        }
        expected_metadata = {"transport": "test", "error_context": "method_missing"}

        # Create and store a pending future
        future = asyncio.Future()
        self.session._pending_requests[request_id] = future

        # Act
        await self.session._handle_response(expected_payload, expected_metadata)

        # Assert
        assert future.done()
        payload, metadata = future.result()
        assert payload == expected_payload
        assert metadata == expected_metadata

    async def test_handles_unmatched_response_gracefully(self):
        # Arrange
        unmatched_id = 999
        unmatched_payload = {
            "jsonrpc": "2.0",
            "id": unmatched_id,
            "result": {"data": "no matching request"},
        }
        metadata = {"transport": "test"}

        # Ensure no pending request exists for this ID
        assert unmatched_id not in self.session._pending_requests

        # Act
        await self.session._handle_response(unmatched_payload, metadata)

        # Assert
        # Should complete without error and not create any futures
        assert unmatched_id not in self.session._pending_requests
        assert len(self.session._pending_requests) == 0

    async def test_resolves_multiple_responses_with_correct_id_matching(self):
        # Arrange
        # Create multiple pending requests with different IDs
        request_ids = [100, 200, 300]
        futures = {}

        for request_id in request_ids:
            future = asyncio.Future()
            futures[request_id] = future
            self.session._pending_requests[request_id] = future

        # Create responses for each request
        responses = [
            (
                {"jsonrpc": "2.0", "id": 100, "result": {"data": "first"}},
                {"meta": "first"},
            ),
            (
                {
                    "jsonrpc": "2.0",
                    "id": 200,
                    "error": {"code": -1, "message": "second"},
                },
                {"meta": "second"},
            ),
            (
                {"jsonrpc": "2.0", "id": 300, "result": {"data": "third"}},
                {"meta": "third"},
            ),
        ]

        # Act
        for payload, metadata in responses:
            await self.session._handle_response(payload, metadata)

        # Assert
        # Each future should resolve with its corresponding response
        for i, request_id in enumerate(request_ids):
            assert futures[request_id].done()
            payload, metadata = futures[request_id].result()
            expected_payload, expected_metadata = responses[i]
            assert payload == expected_payload
            assert metadata == expected_metadata

        # All pending requests should be resolved
        assert len(self.session._pending_requests) == 3


class TestNotificationHandler(BaseSessionTest):
    async def test_parses_and_queues_known_notification(self):
        # Arrange
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {"progressToken": "test-token", "progress": 0.5, "total": 1.0},
        }
        metadata = {"transport": "test", "timestamp": "2025-01-01"}

        # Ensure queue starts empty
        assert self.session.notifications.empty()

        # Act
        await self.session._handle_notification(payload, metadata)

        # Assert
        assert not self.session.notifications.empty()
        notification, queued_metadata = await self.session.notifications.get()

        # Verify we got the right notification type
        assert isinstance(notification, ProgressNotification)
        assert notification.progress_token == "test-token"
        assert notification.progress == 0.5
        assert notification.total == 1.0

        # Verify metadata was preserved
        assert queued_metadata == metadata

    async def test_raises_on_unknown_notification_method(self):
        # Arrange
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/unknown_method",
            "params": {"some": "data"},
        }
        metadata = {"transport": "test"}

        # Ensure queue starts empty
        assert self.session.notifications.empty()

        # Act & Assert
        with pytest.raises(UnknownNotificationError) as exc_info:
            await self.session._handle_notification(payload, metadata)

        # Verify the exception contains the unknown method
        assert "notifications/unknown_method" in str(exc_info.value)

        # Verify nothing was queued when parsing failed
        assert self.session.notifications.empty()


class TestRequestHandler(BaseSessionTest):
    # Core request handling flow
    async def test_sends_success_response_for_valid_ping_request(self):
        # Arrange
        request_payload = {"jsonrpc": "2.0", "id": 42, "method": "ping"}
        transport_metadata = {"transport": "test"}

        # Ensure no messages sent yet
        assert len(self.transport.client_sent_messages) == 0

        # Act
        await self.session._handle_request(request_payload, transport_metadata)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        sent_message = self.transport.client_sent_messages[0]
        response_payload = sent_message.payload

        # Verify JSON-RPC response structure
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == 42
        assert "result" in response_payload
        assert "error" not in response_payload

        # Verify response metadata is None (not echoed)
        assert sent_message.metadata is None

    # Error handling
    async def test_sends_method_not_found_for_unknown_request_method(self):
        # Arrange
        request_payload = {"jsonrpc": "2.0", "id": 123, "method": "unknown/method"}
        transport_metadata = {"transport": "test"}

        # Ensure no messages sent yet
        assert len(self.transport.client_sent_messages) == 0

        # Act
        await self.session._handle_request(request_payload, transport_metadata)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        sent_message = self.transport.client_sent_messages[0]
        response_payload = sent_message.payload

        # Verify JSON-RPC error response structure
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == 123
        assert "error" in response_payload
        assert "result" not in response_payload

        # Verify METHOD_NOT_FOUND error
        error = response_payload["error"]
        assert error["code"] == METHOD_NOT_FOUND
        assert "Unknown request method: unknown/method" in error["message"]

        # Verify response metadata is None
        assert sent_message.metadata is None

    async def test_sends_internal_error_when_handler_raises_exception(
        self, monkeypatch
    ):
        # Arrange
        request_payload = {"jsonrpc": "2.0", "id": 456, "method": "ping"}
        transport_metadata = {"transport": "test"}

        # Mock the ping handler to raise an exception
        async def failing_handler(request: PingRequest):
            raise ValueError("Something went wrong in handler")

        monkeypatch.setattr(self.session, "_handle_ping", failing_handler)

        # Ensure no messages sent yet
        assert len(self.transport.client_sent_messages) == 0

        # Act
        await self.session._handle_request(request_payload, transport_metadata)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        sent_message = self.transport.client_sent_messages[0]
        response_payload = sent_message.payload

        # Verify JSON-RPC error response structure
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == 456
        assert "error" in response_payload
        assert "result" not in response_payload

        # Verify INTERNAL_ERROR
        error = response_payload["error"]
        assert error["code"] == INTERNAL_ERROR
        assert "Internal error processing request" in error["message"]

        # Verify response metadata is None
        assert sent_message.metadata is None

    # Capability-specific handling
    async def test_sends_success_response_for_list_roots_with_capability(self):
        # Arrange
        # Set up session with roots capability
        self.session.capabilities.roots = RootsCapability()
        self.session.roots = [Root(uri="file:///tmp", name="temp")]

        request_payload = {"jsonrpc": "2.0", "id": 789, "method": "roots/list"}

        # Act
        await self.session._handle_request(request_payload, None)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        sent_message = self.transport.client_sent_messages[0]
        response_payload = sent_message.payload

        # Verify successful response
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == 789
        assert "result" in response_payload
        assert "error" not in response_payload

        # Verify roots are included in result
        result = response_payload["result"]
        assert "roots" in result
        assert len(result["roots"]) == 1
        assert result["roots"][0]["uri"] == "file:///tmp"
        assert result["roots"][0]["name"] == "temp"

    async def test_sends_method_not_found_for_list_roots_without_capability(self):
        # Arrange
        # Ensure session has no roots capability
        self.session.capabilities.roots = None

        request_payload = {"jsonrpc": "2.0", "id": 101, "method": "roots/list"}

        # Act
        await self.session._handle_request(request_payload, None)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        sent_message = self.transport.client_sent_messages[0]
        response_payload = sent_message.payload

        # Verify error response
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == 101
        assert "error" in response_payload
        assert "result" not in response_payload

        # Verify METHOD_NOT_FOUND error with capability message
        error = response_payload["error"]
        assert error["code"] == METHOD_NOT_FOUND
        assert "Client does not support roots capability" in error["message"]

        # Verify response metadata is None
        assert sent_message.metadata is None

    async def test_sends_method_not_found_for_create_message_without_capability(self):
        # Arrange
        # Ensure session has no sampling capability
        self.session.capabilities.sampling = False

        request_payload = {
            "jsonrpc": "2.0",
            "id": 202,
            "method": "sampling/createMessage",
            "params": {
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": "Hello"}}
                ],
                "maxTokens": 100,
            },
        }

        # Act
        await self.session._handle_request(request_payload, None)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        sent_message = self.transport.client_sent_messages[0]
        response_payload = sent_message.payload

        # Verify error response
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == 202
        assert "error" in response_payload
        assert "result" not in response_payload

        # Verify METHOD_NOT_FOUND error with capability message
        error = response_payload["error"]
        assert error["code"] == METHOD_NOT_FOUND
        assert "Client does not support sampling capability" in error["message"]

    async def test_sends_success_response_for_create_message_with_capability(
        self, monkeypatch
    ):
        # Arrange
        # Set up session with sampling capability
        self.session.capabilities.sampling = True

        # Mock the create message handler to return a successful result
        mock_result = CreateMessageResult(
            model="test-model",
            role="assistant",
            content=TextContent(type="text", text="Hello! How can I help you?"),
        )

        async def mock_handler(request: CreateMessageRequest):
            return mock_result

        monkeypatch.setattr(self.session, "_create_message_handler", mock_handler)

        request_payload = {
            "jsonrpc": "2.0",
            "id": 303,
            "method": "sampling/createMessage",
            "params": {
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": "Hello"}}
                ],
                "maxTokens": 100,
            },
        }

        # Act
        await self.session._handle_request(request_payload, None)

        # Assert
        assert len(self.transport.client_sent_messages) == 1

        sent_message = self.transport.client_sent_messages[0]
        response_payload = sent_message.payload

        # Verify successful response
        assert response_payload["jsonrpc"] == "2.0"
        assert response_payload["id"] == 303
        assert "result" in response_payload
        assert "error" not in response_payload

        # Verify the result contains expected fields
        result = response_payload["result"]
        assert result["model"] == "test-model"
        assert result["role"] == "assistant"
        assert result["content"]["type"] == "text"
        assert result["content"]["text"] == "Hello! How can I help you?"


class TestMessageValidators(BaseSessionTest):
    def test_is_valid_response_identifies_success_responses(self):
        # Arrange
        valid_response = {"jsonrpc": "2.0", "id": 42, "result": {"data": "success"}}

        # Act & Assert
        assert self.session._is_valid_response(valid_response) is True

    def test_is_valid_response_identifies_error_responses(self):
        # Arrange
        valid_error_response = {
            "jsonrpc": "2.0",
            "id": 123,
            "error": {"code": -32601, "message": "Method not found"},
        }

        # Act & Assert
        assert self.session._is_valid_response(valid_error_response) is True

    def test_is_valid_response_rejects_both_result_and_error(self):
        # Arrange
        invalid_response = {
            "jsonrpc": "2.0",
            "id": 42,
            "result": {"data": "success"},
            "error": {"code": -1, "message": "Also an error"},  # Invalid per spec
        }

        # Act & Assert
        assert self.session._is_valid_response(invalid_response) is False

    def test_is_valid_request_identifies_valid_requests(self):
        # Arrange
        valid_request = {"jsonrpc": "2.0", "method": "ping", "id": 42, "params": {}}

        # Act & Assert
        assert self.session._is_valid_request(valid_request) is True

    def test_is_valid_request_rejects_missing_method(self):
        # Arrange
        invalid_request = {
            "jsonrpc": "2.0",
            "id": 42,
            "params": {},
            # Missing method
        }

        # Act & Assert
        assert self.session._is_valid_request(invalid_request) is False

    def test_is_valid_request_rejects_missing_id(self):
        # Arrange
        invalid_request = {
            "jsonrpc": "2.0",
            "method": "ping",
            "params": {},
            # Missing id
        }

        # Act & Assert
        assert self.session._is_valid_request(invalid_request) is False

    def test_is_valid_request_rejects_null_id(self):
        # Arrange
        invalid_request = {
            "jsonrpc": "2.0",
            "method": "ping",
            "id": None,  # Null id
            "params": {},
        }

        # Act & Assert
        assert self.session._is_valid_request(invalid_request) is False

    def test_is_valid_notification_identifies_valid_notifications(self):
        # Arrange
        valid_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {"progress": 0.5},
            # No id field
        }

        # Act & Assert
        assert self.session._is_valid_notification(valid_notification) is True

    def test_is_valid_notification_rejects_missing_method(self):
        # Arrange
        invalid_notification = {
            "jsonrpc": "2.0",
            "params": {"progress": 0.5},
            # Missing method
        }

        # Act & Assert
        assert self.session._is_valid_notification(invalid_notification) is False

    def test_is_valid_notification_rejects_notifications_with_id(self):
        # Arrange
        invalid_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "id": 42,  # Should not have id
            "params": {"progress": 0.5},
        }

        # Act & Assert
        assert self.session._is_valid_notification(invalid_notification) is False

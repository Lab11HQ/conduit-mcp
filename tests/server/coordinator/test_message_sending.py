import asyncio

import pytest

from conduit.protocol.base import Error, Result
from conduit.protocol.common import CancelledNotification, PingRequest


class TestRequestSending:
    async def test_starts_coordinator(self, coordinator, yield_loop):
        # Arrange
        request = PingRequest()
        client_id = "test_client"
        assert not coordinator.running

        # Act - send request in background
        asyncio.create_task(
            coordinator.send_request_to_client(client_id, request, timeout=1.0)
        )

        # Give coordinator time to send the request
        await yield_loop()

        # Assert
        assert coordinator.running

    async def test_tracks_request_to_client_and_returns_result(
        self, coordinator, mock_transport, client_manager, yield_loop
    ):
        # Arrange
        request = PingRequest()
        client_id = "test_client"

        # Act - send request in background
        request_task = asyncio.create_task(
            coordinator.send_request_to_client(client_id, request, timeout=1.0)
        )

        # Give coordinator time to send the request
        await yield_loop()

        # Assert - request was sent to transport
        sent_messages = mock_transport.sent_messages.get(client_id, [])
        assert len(sent_messages) == 1

        sent_request = sent_messages[0]
        request_id = sent_request["id"]
        assert sent_request["method"] == "ping"

        # Assert - client was registered and request is tracked
        assert client_manager.get_client(client_id) is not None
        assert client_manager.get_request_to_client(client_id, request_id) is not None

        # Act - simulate client response
        response_payload = {"jsonrpc": "2.0", "id": request_id, "result": {}}
        mock_transport.add_client_message(client_id, response_payload)

        # Give coordinator time to process response
        await yield_loop()

        # Assert - request completes successfully
        result = await request_task
        assert isinstance(result, Result)

        # Assert - request is no longer tracked
        assert client_manager.get_request_to_client(client_id, request_id) is None

    async def test_returns_error_response_from_client(
        self, coordinator, mock_transport, client_manager, yield_loop
    ):
        # Arrange
        request = PingRequest()
        client_id = "test_client"

        # Act - send request in background
        request_task = asyncio.create_task(
            coordinator.send_request_to_client(client_id, request, timeout=1.0)
        )

        # Give coordinator time to send the request
        await yield_loop()

        # Assert - request was sent to transport
        sent_messages = mock_transport.sent_messages.get(client_id, [])
        assert len(sent_messages) == 1

        sent_request = sent_messages[0]
        request_id = sent_request["id"]

        # Assert - request is tracked
        assert client_manager.get_request_to_client(client_id, request_id) is not None

        # Act - simulate client error response
        error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": "Method not found",
                "data": {"details": "Unknown method"},
            },
        }
        mock_transport.add_client_message(client_id, error_response)

        # Give coordinator time to process response
        await yield_loop()

        # Assert - error response returned as Error object
        result = await request_task
        assert isinstance(result, Error)
        assert result.code == -32601
        assert result.message == "Method not found"
        assert result.data == {"details": "Unknown method"}

        # Assert - request is no longer tracked
        assert client_manager.get_request_to_client(client_id, request_id) is None

    async def test_timeout_raises_and_cancels(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange
        request = PingRequest()
        client_id = "test_client"

        # Act & Assert - timeout should raise
        with pytest.raises(asyncio.TimeoutError):
            await coordinator.send_request_to_client(client_id, request, timeout=0.03)

        # Give coordinator time to send cancellation
        await yield_loop()

        # Assert - two messages were sent
        sent_messages = mock_transport.sent_messages.get(client_id, [])
        assert len(sent_messages) == 2

        # Assert - original request was sent
        ping_message = sent_messages[0]
        assert ping_message["method"] == "ping"

        # Assert - cancellation notification was sent
        cancellation_msg = sent_messages[1]
        assert cancellation_msg["method"] == "notifications/cancelled"
        assert "timed out" in cancellation_msg["params"]["reason"]

    async def test_raises_connection_error_when_transport_closed(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange
        request = PingRequest()
        client_id = "test_client"

        # Act - close the transport
        await mock_transport.close()
        await yield_loop()

        # Act & Assert
        with pytest.raises(ConnectionError):
            await coordinator.send_request_to_client(client_id, request)

        # Assert - no messages were sent
        sent_messages = mock_transport.sent_messages.get(client_id, [])
        assert len(sent_messages) == 0

    async def test_cleans_up_tracking_when_transport_send_fails(
        self, coordinator, mock_transport, client_manager
    ):
        # Arrange
        request = PingRequest()
        client_id = "test_client"

        async def failing_send(client_id, message):
            raise ConnectionError("Test network failure")

        mock_transport.send_to_client = failing_send

        # Act & Assert - should raise the transport error
        with pytest.raises(ConnectionError, match="Test network failure"):
            await coordinator.send_request_to_client(client_id, request, timeout=1.0)

        # Assert - request is no longer tracked
        client_context = client_manager.get_client(client_id)
        assert client_context is not None
        assert len(client_context.requests_to_client) == 0


class TestNotificationSending:
    async def test_starts_coordinator(self, coordinator):
        # Arrange
        notification = CancelledNotification(
            request_id="test-123", reason="user cancelled"
        )
        client_id = "test_client"
        assert not coordinator.running

        # Act
        await coordinator.send_notification_to_client(client_id, notification)

        # Assert
        assert coordinator.running

    async def test_sends_successfully(self, coordinator, mock_transport):
        # Arrange
        notification = CancelledNotification(
            request_id="test-123", reason="user cancelled"
        )
        client_id = "test_client"

        # Act
        await coordinator.send_notification_to_client(client_id, notification)

        # Assert - notification was sent to transport
        sent_messages = mock_transport.sent_messages.get(client_id, [])
        assert len(sent_messages) == 1
        sent_notification = sent_messages[0]
        assert sent_notification["method"] == "notifications/cancelled"

    async def test_raises_connection_error_when_transport_closed(
        self, coordinator, mock_transport
    ):
        # Arrange
        notification = CancelledNotification(
            request_id="test-123", reason="user cancelled"
        )
        client_id = "test_client"

        # Close the transport
        await mock_transport.close()

        # Act & Assert - should raise ConnectionError
        with pytest.raises(ConnectionError):
            await coordinator.send_notification_to_client(client_id, notification)

        # Assert - no messages were sent
        sent_messages = mock_transport.sent_messages.get(client_id, [])
        assert len(sent_messages) == 0

    async def test_propagates_transport_send_error(self, coordinator, mock_transport):
        # Arrange
        notification = CancelledNotification(
            request_id="test-123", reason="user cancelled"
        )
        client_id = "test_client"

        async def failing_send(client_id, message):
            raise ConnectionError("Test network failure")

        mock_transport.send_to_client = failing_send

        # Act & Assert - should raise the transport error
        with pytest.raises(ConnectionError, match="Test network failure"):
            await coordinator.send_notification_to_client(client_id, notification)

        # Assert - no messages were sent
        sent_messages = mock_transport.sent_messages.get(client_id, [])
        assert len(sent_messages) == 0

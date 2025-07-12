import asyncio

import pytest

from conduit.protocol.base import PROTOCOL_VERSION, Error, Result
from conduit.protocol.common import CancelledNotification, PingRequest
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializeRequest,
)


class TestRequestSending:
    async def test_starts_coordinator(self, coordinator, yield_loop):
        # Arrange
        request = PingRequest()
        assert not coordinator.running

        # Act
        asyncio.create_task(coordinator.send_request(request))

        # Give coordinator time to send the request
        await yield_loop()

        # Assert
        assert coordinator.running

    async def test_tracks_request_to_server_and_returns_result(
        self, coordinator, mock_transport, server_manager, yield_loop
    ):
        # Arrange
        request = PingRequest()

        # Act
        request_task = asyncio.create_task(coordinator.send_request(request))

        # Give coordinator time to send the request
        await yield_loop()

        # Assert - request was sent to transport
        sent_messages = mock_transport.sent_messages
        assert len(sent_messages) == 1

        sent_request = sent_messages[0]
        assert sent_request["method"] == "ping"
        request_id = sent_request["id"]

        # Assert - request is tracked
        assert server_manager.get_request_to_server(request_id) is not None

        # Act - simulate server response
        response_payload = {"jsonrpc": "2.0", "id": request_id, "result": {}}
        mock_transport.add_server_message(response_payload)

        # Assert - request completes successfully
        result = await request_task
        assert isinstance(result, Result)

        # Assert - request tracking was cleaned up
        assert server_manager.get_request_to_server(request_id) is None

    async def test_returns_error_response_from_server(
        self, coordinator, mock_transport, server_manager, yield_loop
    ):
        # Arrange
        request = PingRequest()

        # Act
        request_task = asyncio.create_task(coordinator.send_request(request))

        # Give coordinator time to send the request
        await yield_loop()

        # Assert - request was sent to transport
        sent_messages = mock_transport.sent_messages
        request_id = sent_messages[0]["id"]
        assert len(sent_messages) == 1

        # Assert - request is tracked
        assert server_manager.get_request_to_server(request_id) is not None

        # Act - simulate server error response
        error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": "Method not found",
                "data": {"details": "Unknown method"},
            },
        }
        mock_transport.add_server_message(error_response)

        # Assert - error response returned as Error object
        result = await request_task
        assert isinstance(result, Error)
        assert result.code == -32601
        assert result.message == "Method not found"

        # Assert - request tracking was cleaned up
        assert server_manager.get_request_to_server(request_id) is None

    async def test_timeout_does_not_cancel_initialization_request(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange
        request = InitializeRequest(
            protocol_version=PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(
                name="test",
                version="1.0.0",
            ),
        )

        # Act & Assert
        with pytest.raises(asyncio.TimeoutError):
            await coordinator.send_request(request, timeout=0.02)

        await yield_loop()

        # Assert - Did not send cancellation notification
        sent_messages = mock_transport.sent_messages
        assert len(sent_messages) == 1

        # Assert - original request was sent
        initialize_message = sent_messages[0]
        assert initialize_message["method"] == "initialize"

    async def test_timeout_cancels_non_initialization_request(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange
        request = PingRequest()

        # Act & Assert
        with pytest.raises(asyncio.TimeoutError):
            await coordinator.send_request(request, timeout=0.02)

        await yield_loop()

        # Assert - two messages were sent
        sent_messages = mock_transport.sent_messages
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

        # Close the transport
        await mock_transport.close()
        await yield_loop()

        # Act & Assert - should raise ConnectionError
        with pytest.raises(ConnectionError):
            await coordinator.send_request(request)

        # Assert - no messages were sent
        sent_messages = mock_transport.sent_messages
        assert len(sent_messages) == 0

    async def test_cleans_up_tracking_when_transport_fails(
        self, coordinator, mock_transport, server_manager
    ):
        # Arrange
        request = PingRequest()

        async def failing_send(message):
            raise ConnectionError("Test network failure")

        mock_transport.send_to_server = failing_send

        # Act & Assert - should raise the transport error
        with pytest.raises(ConnectionError, match="Test network failure"):
            await coordinator.send_request(request, timeout=1.0)

        # Assert
        server_context = server_manager.get_server_context()
        assert len(server_context.requests_to_server) == 0


class TestNotificationSending:
    async def test_starts_coordinator(self, coordinator):
        # Arrange
        notification = CancelledNotification(
            request_id="test-123", reason="user cancelled"
        )
        assert not coordinator.running

        # Act
        await coordinator.send_notification(notification)

        # Assert
        assert coordinator.running

    async def test_sends_successfully(self, coordinator, mock_transport):
        # Arrange
        notification = CancelledNotification(
            request_id="test-123", reason="user cancelled"
        )

        # Act
        await coordinator.send_notification(notification)

        # Assert - notification was sent to transport
        sent_messages = mock_transport.sent_messages
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

        # Act - close the transport
        await mock_transport.close()

        # Act & Assert
        with pytest.raises(ConnectionError):
            await coordinator.send_notification(notification)

        # Assert
        assert len(mock_transport.sent_messages) == 0

    async def test_propagates_transport_send_error(self, coordinator, mock_transport):
        # Arrange
        notification = CancelledNotification(
            request_id="test-123", reason="user cancelled"
        )

        async def failing_send(message):
            raise ConnectionError("Network failure")

        mock_transport.send_to_server = failing_send

        # Act & Assert
        with pytest.raises(ConnectionError, match="Network failure"):
            await coordinator.send_notification(notification)

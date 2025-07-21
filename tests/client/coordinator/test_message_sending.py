import asyncio

import pytest

from conduit.protocol.base import PROTOCOL_VERSION, Error, Result
from conduit.protocol.common import CancelledNotification, PingRequest
from conduit.protocol.initialization import (
    ClientCapabilities,
    Implementation,
    InitializeRequest,
)
from conduit.protocol.tools import ListToolsRequest


class TestRequestSending:
    async def test_send_fails_when_not_running(self, coordinator):
        # Arrange
        request = PingRequest()
        server_id = "server1"
        assert not coordinator.running

        # Act & Assert
        with pytest.raises(RuntimeError):
            await coordinator.send_request(server_id, request)

    async def test_tracks_request_to_server_and_returns_result(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange
        await coordinator.start()
        server_id = "server1"

        # Register server in coordinator's manager and transport
        coordinator.server_manager.register_server(server_id)
        await mock_transport.add_server(server_id, {"host": "test-host", "port": 8080})

        # Act
        request_task = asyncio.create_task(
            coordinator.send_request(server_id, PingRequest())
        )

        # Give coordinator time to send the request
        await yield_loop()

        # Assert - request was sent to transport
        sent_messages = mock_transport.sent_messages.get(server_id, [])
        assert len(sent_messages) == 1

        sent_request = sent_messages[0]
        request_id = sent_request["id"]
        assert sent_request["method"] == "ping"

        # Assert - request is tracked in coordinator's manager
        assert (
            coordinator.server_manager.get_request_to_server(server_id, request_id)
            is not None
        )

        # Act - simulate server response
        response_payload = {"jsonrpc": "2.0", "id": request_id, "result": {}}
        mock_transport.add_server_message(server_id, response_payload)

        # Assert - request completes successfully
        result = await request_task
        assert isinstance(result, Result)

        # Assert - request tracking was cleaned up
        assert (
            coordinator.server_manager.get_request_to_server(server_id, request_id)
            is None
        )

    async def test_returns_error_response_from_server(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange
        await coordinator.start()
        request = ListToolsRequest()
        server_id = "server1"

        # Register server in coordinator's manager and transport
        coordinator.server_manager.register_server(server_id)
        await mock_transport.add_server(server_id, {"host": "test-host", "port": 8080})

        # Act
        request_task = asyncio.create_task(coordinator.send_request(server_id, request))

        # Give coordinator time to send the request
        await yield_loop()

        # Assert - request was sent to transport
        sent_messages = mock_transport.sent_messages.get(server_id, [])
        request_id = sent_messages[0]["id"]
        assert len(sent_messages) == 1

        # Assert - request is tracked
        assert (
            coordinator.server_manager.get_request_to_server(server_id, request_id)
            is not None
        )

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
        mock_transport.add_server_message(server_id, error_response)

        # Give coordinator time to process response
        await yield_loop()

        # Assert - error response returned as Error object
        result = await request_task
        assert isinstance(result, Error)
        assert result.code == -32601
        assert result.message == "Method not found"

        # Assert - request tracking was cleaned up
        assert (
            coordinator.server_manager.get_request_to_server(server_id, request_id)
            is None
        )

    async def test_timeout_does_not_cancel_initialization_request(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange
        await coordinator.start()
        request = InitializeRequest(
            protocol_version=PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(
                name="test",
                version="1.0.0",
            ),
        )
        server_id = "server1"

        # Register server in coordinator's manager and transport
        coordinator.server_manager.register_server(server_id)
        await mock_transport.add_server(server_id, {"host": "localhost", "port": 8080})

        # Act & Assert
        with pytest.raises(asyncio.TimeoutError):
            await coordinator.send_request(server_id, request, timeout=0.02)

        await yield_loop()

        # Assert - Did not send cancellation notification
        sent_messages = mock_transport.sent_messages.get(server_id, [])
        assert len(sent_messages) == 1

        # Assert - original request was sent
        initialize_message = sent_messages[0]
        assert initialize_message["method"] == "initialize"

    async def test_timeout_cancels_non_initialization_request(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange
        await coordinator.start()
        server_id = "server1"

        # Register server in coordinator's manager and transport
        coordinator.server_manager.register_server(server_id)
        await mock_transport.add_server(server_id, {"host": "test-host", "port": 8080})

        request = PingRequest()

        # Act & Assert
        with pytest.raises(asyncio.TimeoutError):
            await coordinator.send_request(server_id, request, timeout=0.02)

        await yield_loop()

        # Assert - two messages were sent
        sent_messages = mock_transport.sent_messages.get(server_id, [])
        assert len(sent_messages) == 2

        # Assert - original request was sent
        ping_message = sent_messages[0]
        assert ping_message["method"] == "ping"

        # Assert - cancellation notification was sent
        cancellation_msg = sent_messages[1]
        assert cancellation_msg["method"] == "notifications/cancelled"

    async def test_cleans_up_tracking_when_transport_fails(
        self, coordinator, mock_transport
    ):
        # Arrange
        await coordinator.start()
        server_id = "server1"

        # Register server in coordinator's manager and transport
        coordinator.server_manager.register_server(server_id)
        await mock_transport.add_server(server_id, {"host": "localhost", "port": 8080})

        mock_transport.simulate_error()

        # Act & Assert - should raise the transport error
        with pytest.raises(ConnectionError):
            await coordinator.send_request(server_id, PingRequest(), timeout=1.0)

        # Assert
        assert (
            coordinator.server_manager.request_tracker.get_peer_outbound_request_ids(
                server_id
            )
            == []
        )


class TestNotificationSending:
    async def test_send_fails_when_not_running(self, coordinator):
        # Arrange
        notification = CancelledNotification(
            request_id="test-123", reason="user cancelled"
        )
        server_id = "server1"
        assert not coordinator.running

        # Act & Assert
        with pytest.raises(RuntimeError):
            await coordinator.send_notification(server_id, notification)

    async def test_sends_successfully_when_running(self, coordinator, mock_transport):
        # Arrange
        await coordinator.start()
        notification = CancelledNotification(
            request_id="test-123", reason="user cancelled"
        )
        server_id = "server1"

        # Register server in coordinator's manager and transport
        coordinator.server_manager.register_server(server_id)
        await mock_transport.add_server(server_id, {"host": "test-host", "port": 8080})

        # Act
        await coordinator.send_notification(server_id, notification)

        # Assert - notification was sent to transport
        sent_messages = mock_transport.sent_messages.get(server_id, [])
        assert len(sent_messages) == 1
        sent_notification = sent_messages[0]
        assert sent_notification["method"] == "notifications/cancelled"

    async def test_propagates_transport_error(self, coordinator, mock_transport):
        # Arrange
        await coordinator.start()
        notification = CancelledNotification(
            request_id="test-123", reason="user cancelled"
        )
        server_id = "server1"

        # Register server in coordinator's manager and transport
        coordinator.server_manager.register_server(server_id)
        await mock_transport.add_server(server_id, {"host": "test-host", "port": 8080})

        mock_transport.simulate_error()

        # Act & Assert
        with pytest.raises(ConnectionError):
            await coordinator.send_notification(server_id, notification)

        sent_messages = mock_transport.sent_messages.get(server_id, [])
        assert len(sent_messages) == 0

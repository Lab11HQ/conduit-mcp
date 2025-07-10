from unittest.mock import AsyncMock

from conduit.protocol.common import CancelledNotification


class TestNotificationHandling:
    async def test_routes_notification_to_registered_handler(
        self, coordinator, yield_loop
    ):
        """Test that notifications are parsed and routed to registered handlers."""
        # Arrange
        await coordinator.start()
        client_id = "test_client"

        # Create a mock handler
        mock_handler = AsyncMock()
        coordinator.register_notification_handler(
            "notifications/cancelled", mock_handler
        )

        # Create notification payload
        notification_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {
                "requestId": "test-request-123",
                "reason": "User cancelled operation",
            },
        }

        # Act
        await coordinator._handle_notification(client_id, notification_payload)

        # Give the background task time to run
        await yield_loop()

        # Assert
        mock_handler.assert_awaited_once()
        call_args = mock_handler.call_args

        # Verify handler was called with correct client_id
        assert call_args[0][0] == client_id

        # Verify handler was called with parsed notification
        parsed_notification = call_args[0][1]
        assert isinstance(parsed_notification, CancelledNotification)
        assert parsed_notification.request_id == "test-request-123"
        assert parsed_notification.reason == "User cancelled operation"

    async def test_ignores_notification_with_parse_failure(
        self, coordinator, monkeypatch
    ):
        """Test that notifications with parse failures are ignored gracefully."""
        # Arrange
        await coordinator.start()
        client_id = "test_client"

        # Mock the parser to return None (parse failure)
        monkeypatch.setattr(
            coordinator.parser, "parse_notification", lambda payload: None
        )

        # Create notification payload
        notification_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": "test-123"},
        }

        # Act & Assert - should handle gracefully without raising
        await coordinator._handle_notification(client_id, notification_payload)

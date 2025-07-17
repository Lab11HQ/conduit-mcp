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

    async def test_ignores_notification_with_parse_failure(self, coordinator):
        """Test that notifications with parse failures are ignored gracefully."""
        # Arrange
        client_id = "test_client"
        invalid_notification = {
            "jsonrpc": "2.0",
            "method": "not/a/real/notification",
            "params": {"some": "data"},
        }

        # Verify the parser fails on this payload
        parsed_notification = coordinator.parser.parse_notification(
            invalid_notification
        )
        assert parsed_notification is None

        # Act - call handler directly with the payload that we know will fail parsing
        await coordinator._handle_notification(client_id, invalid_notification)

        # Assert - should handle gracefully (no exceptions raised)
        # The test passes if we get here without exceptions
        assert True

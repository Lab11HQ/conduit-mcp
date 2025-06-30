from conduit.protocol.logging import LoggingMessageNotification

from .conftest import BaseSessionTest


class TestSendNotification(BaseSessionTest):
    """Test the send_notification method."""

    async def test_sends_notification_to_transport(self):
        """Notifications are properly serialized and sent to transport."""
        # Arrange
        notification = LoggingMessageNotification(
            level="info", data="Test message", logger="test-logger"
        )

        # Act
        await self.session.send_notification(notification)

        # Assert
        assert len(self.transport.sent_messages) == 1
        sent_message = self.transport.sent_messages[0]

        assert sent_message["jsonrpc"] == "2.0"
        assert sent_message["method"] == "notifications/message"
        assert "id" not in sent_message  # Notifications don't have IDs
        assert sent_message["params"]["level"] == "info"
        assert sent_message["params"]["data"] == "Test message"

    async def test_starts_session_automatically(self):
        """Session is started automatically if not already running."""
        # Arrange
        assert not self.session.running
        notification = LoggingMessageNotification(
            level="info", data="Test", logger="test"
        )

        # Act
        await self.session.send_notification(notification)

        # Assert
        assert self.session.running
        assert len(self.transport.sent_messages) == 1

    async def test_works_when_session_already_running(self):
        """Sending notifications works when session is already started."""
        # Arrange
        await self.session.start()
        assert self.session.running

        notification = LoggingMessageNotification(
            level="info", data="Test", logger="test"
        )

        # Act
        await self.session.send_notification(notification)

        # Assert
        assert self.session.running
        assert len(self.transport.sent_messages) == 1

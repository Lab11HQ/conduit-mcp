import pytest

from conduit.protocol.common import ProgressNotification
from conduit.shared.exceptions import UnknownNotificationError

from .conftest import BaseSessionTest


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


class TestNotificationValidator(BaseSessionTest):
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

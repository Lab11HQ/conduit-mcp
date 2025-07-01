import pytest

from conduit.shared.exceptions import UnknownNotificationError
from tests.client.session.conftest import ClientSessionTest


class TestNotificationRouting(ClientSessionTest):
    async def test_raises_error_for_unknown_notification_method(self):
        # Arrange
        unknown_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/unknown",
            "params": {},
        }

        # Act & Assert
        with pytest.raises(UnknownNotificationError, match="notifications/unknown"):
            await self.session._handle_session_notification(unknown_notification)

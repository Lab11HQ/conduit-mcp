import asyncio

import pytest

from conduit.protocol.base import Error
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.logging import SetLevelRequest
from conduit.protocol.roots import RootsListChangedNotification
from conduit.protocol.tools import ListToolsRequest

from .conftest import BaseSessionTest


class TestSendRequest(BaseSessionTest):
    """Tests for ClientSession.send_request method."""

    @pytest.fixture(autouse=True)
    def mock_uuid4(self, monkeypatch):
        """Mock uuid.uuid4 to return a predictable value."""

        id_generator = iter(f"test-id-{i}" for i in range(1, 100))

        monkeypatch.setattr(
            "conduit.client.session.uuid.uuid4", lambda: next(id_generator)
        )

    async def test_starts_session_if_not_started(self):
        """send_request starts the session automatically.

        Also verifies that PingRequests work before initialization, as allowed by
        the MCP spec.
        """
        # Arrange
        assert not self.session._running
        request = PingRequest()

        # Act - start the request and let it run in background
        request_task = asyncio.create_task(self.session.send_request(request))

        # Wait for ping to be sent, then respond
        await self.wait_for_sent_message("ping")
        self.server.send_message({"jsonrpc": "2.0", "id": "test-id-1", "result": {}})

        # Wait for completion
        result = await request_task

        # Assert
        assert self.session._running
        assert isinstance(result, EmptyResult)

    async def test_returns_immediately_for_no_response_requests(self):
        """Requests without expected responses return None immediately."""
        # Arrange
        self.session._initialize_result = "NOT NONE"

        request = SetLevelRequest(level="info")

        # Act
        result = await self.session.send_request(request)

        # Assert
        assert result is None

        # Verify the request was actually sent
        await self.wait_for_sent_message("logging/setLevel")
        sent_message = self.transport.client_sent_messages[-1]
        assert sent_message["method"] == "logging/setLevel"
        assert sent_message["params"]["level"] == "info"
        assert "id" in sent_message  # Should still have an ID

    async def test_raises_runtime_error_for_non_ping_before_init(self):
        """Non-ping requests fail before initialization."""
        # Arrange
        assert not self.session.initialized
        request = ListToolsRequest()  # Any non-ping request

        # Act & Assert
        with pytest.raises(
            RuntimeError,
            match="Session must be initialized before sending non-ping requests",
        ):
            await self.session.send_request(request)

        # Verify nothing was sent
        assert len(self.transport.client_sent_messages) == 0

    async def test_timeout_sends_cancellation_and_raises_timeout_error(self):
        """Times out waiting for response and sends cancellation notification."""
        # Arrange
        request = PingRequest()

        # Act & Assert
        with pytest.raises(
            TimeoutError, match="Request test-id-1 timed out after 0.05s"
        ):
            # Note: No response is sent from our mock server, so this will timeout.
            await self.session.send_request(request, timeout=0.05)

        # Verify original request was sent
        await self.wait_for_sent_message("ping")

        # Verify cancellation notification was sent
        await self.wait_for_sent_message("notifications/cancelled")

        # Check that we sent two messages
        assert len(self.transport.client_sent_messages) == 2

        # Check the cancellation details
        cancellation_msg = next(
            msg
            for msg in self.transport.client_sent_messages
            if msg.get("method") == "notifications/cancelled"
        )
        assert cancellation_msg["params"]["requestId"] == "test-id-1"
        assert "timed out" in cancellation_msg["params"]["reason"]

    async def test_handles_error_responses_from_server(self):
        """Processes and returns error responses from server."""
        # Arrange
        request = PingRequest()

        # Act - start the request in background
        request_task = asyncio.create_task(self.session.send_request(request))

        # Wait for ping to be sent, then respond with error
        await self.wait_for_sent_message("ping")
        error_response = {
            "jsonrpc": "2.0",
            "id": "test-id-1",
            "error": {
                "code": -32603,
                "message": "Internal error",
                "data": {"details": "Something went wrong"},
            },
        }
        self.server.send_message(error_response)

        # Wait for completion
        result = await request_task

        # Assert
        assert isinstance(result, Error)
        assert result.code == -32603
        assert result.message == "Internal error"
        assert result.data == {"details": "Something went wrong"}

    async def test_cleans_up_pending_requests_on_completion(self):
        """Removes completed requests from pending requests dict."""
        # Arrange
        request = PingRequest()

        # Act
        request_task = asyncio.create_task(self.session.send_request(request))

        # Verify request is tracked while pending
        await self.wait_for_sent_message("ping")
        assert len(self.session._pending_requests) == 1
        assert "test-id-1" in self.session._pending_requests

        # Complete the request
        self.server.send_message({"jsonrpc": "2.0", "id": "test-id-1", "result": {}})
        _ = await request_task

        # Assert cleanup
        assert len(self.session._pending_requests) == 0

    async def test_transport_errors_bubble_up_unchanged(self):
        """Transport failures during send bubble up without modification."""
        # Arrange
        request = PingRequest()

        # Mock transport to raise on send
        async def failing_send(*args, **kwargs):
            raise ConnectionError("Network unreachable")

        self.transport.send = failing_send

        # Act & Assert
        with pytest.raises(ConnectionError, match="Network unreachable"):
            await self.session.send_request(request)

        # Verify no cleanup needed - request never got tracked
        assert len(self.session._pending_requests) == 0

    async def test_timeout_raises_timeout_error_even_if_cancellation_fails(self):
        """TimeoutError is raised even when cancellation notification fails to send."""
        # Arrange
        await self.session._start()
        self.session._initialize_result = "NOT NONE"
        request = PingRequest()

        # Mock transport to fail on second send (the cancellation)
        send_count = 0
        original_send = self.transport.send

        async def selective_failing_send(*args, **kwargs):
            nonlocal send_count
            send_count += 1
            if send_count == 1:
                return await original_send(*args, **kwargs)  # Original request succeeds
            else:
                raise ConnectionError("Transport died")  # Cancellation fails

        self.transport.send = selective_failing_send

        # Act & Assert
        with pytest.raises(
            TimeoutError, match="Request test-id-1 timed out after 0.05s"
        ):
            await self.session.send_request(request, timeout=0.05)

        # Verify both sends were attempted
        assert send_count == 2

        # Verify the first message was the ping
        first_message = self.transport.client_sent_messages[0]
        assert first_message["method"] == "ping"
        assert first_message["id"] == "test-id-1"

        # Note: We can't verify the cancellation message was attempted since
        # the mock transport failed before recording it, but send_count proves
        # it was tried.


class TestSendNotification(BaseSessionTest):
    """Tests for ClientSession.send_notification method."""

    async def test_sends_notification_without_initialization(self):
        """Notifications can be sent before session initialization."""
        # Arrange
        assert not self.session.initialized
        notification = RootsListChangedNotification()

        # Act
        await self.session.send_notification(notification)

        # Assert
        await self.wait_for_sent_message("notifications/roots/list_changed")
        sent_message = self.transport.client_sent_messages[-1]
        assert sent_message["method"] == "notifications/roots/list_changed"
        assert "id" not in sent_message  # No ID for notifications

    async def test_transport_errors_bubble_up_from_notifications(self):
        """Transport failures during notification send bubble up unchanged."""
        # Arrange
        notification = RootsListChangedNotification()

        # Mock transport to fail
        async def failing_send(*args, **kwargs):
            raise ConnectionError("Network down")

        self.transport.send = failing_send

        # Act & Assert
        with pytest.raises(ConnectionError, match="Network down"):
            await self.session.send_notification(notification)

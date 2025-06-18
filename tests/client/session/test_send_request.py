import asyncio

import pytest

from conduit.protocol.base import Error, Result
from conduit.protocol.common import PingRequest
from conduit.protocol.logging import SetLevelRequest

from .conftest import BaseSessionTest


class TestSendRequest(BaseSessionTest):
    """Tests for ClientSession.send_request method."""

    async def test_starts_session_if_not_started(self, mock_ensure_initialized):
        """send_request starts the session automatically."""
        # Arrange
        assert not self.session._running
        request = SetLevelRequest(level="info")

        # Act
        await self.session.send_request(request)

        # Assert
        assert self.session._running

    async def test_allows_ping_before_initialization(self, monkeypatch):
        """PingRequest can be sent before session is initialized."""

        # Arrange
        def numbered_ids():
            return iter(f"test-id-{i}" for i in range(1, 100))

        id_generator = numbered_ids()
        monkeypatch.setattr(
            "conduit.client.session.uuid.uuid4", lambda: next(id_generator)
        )

        request = PingRequest()
        await self.session._start()
        self.session._initialize_result = None  # Ensure not initialized

        # Act & Assert
        async def send_ping_and_respond():
            # Start the request
            task = asyncio.create_task(self.session.send_request(request))
            await self.wait_for_sent_message("ping")

            # Send response
            self.server.send_message(
                {"jsonrpc": "2.0", "id": "test-id-1", "result": {}}
            )

            # Should complete successfully
            result = await task
            assert result is not None  # Got a response

        await send_ping_and_respond()

        # Assert - still not initialized
        assert self.session._initialize_result is None

    async def test_auto_initializes_for_non_ping_requests(
        self, mock_ensure_initialized
    ):
        """Non-ping requests trigger automatic initialization."""
        # Arrange
        request = SetLevelRequest(level="info")  # Fire-and-forget, non-ping
        await self.session._start()
        self.session._initialize_result = None

        # Act
        await self.session.send_request(request)

        # Assert
        assert self.session._initialize_result is not None

    async def test_tracks_requests_that_expect_responses(
        self, mock_ensure_initialized, monkeypatch
    ):
        """Requests expecting responses are tracked in pending requests."""

        # Arrange
        def numbered_ids():
            return iter(f"test-id-{i}" for i in range(1, 100))

        id_generator = numbered_ids()
        monkeypatch.setattr(
            "conduit.client.session.uuid.uuid4", lambda: next(id_generator)
        )

        request = PingRequest()  # Expects a response

        # Act
        task = asyncio.create_task(self.session.send_request(request))
        await self.wait_for_sent_message("ping")

        # Assert - request is tracked
        assert "test-id-1" in self.session._pending_requests
        assert self.session._pending_requests["test-id-1"][0] == request

        # Cleanup
        task.cancel()

    async def test_does_not_track_fire_and_forget_requests(
        self, mock_ensure_initialized
    ):
        """Fire-and-forget requests are not tracked."""
        # Arrange
        request = SetLevelRequest(level="info")
        initial_pending_count = len(self.session._pending_requests)

        # Act
        result = await self.session.send_request(request)

        # Assert - no new pending requests
        assert len(self.session._pending_requests) == initial_pending_count
        assert result is None

    async def test_includes_transport_metadata(self, mock_ensure_initialized):
        """Transport metadata is passed through to transport.send()."""
        # Arrange
        request = SetLevelRequest(level="info")
        metadata = {"auth": "token123"}

        # Act
        await self.session.send_request(request, transport_metadata=metadata)

        # Assert
        sent_message = self.transport.client_sent_messages[0]
        assert sent_message.metadata == metadata

    async def test_sends_request_to_transport(self, mock_ensure_initialized):
        """Request is sent through the transport."""
        # Arrange
        request = SetLevelRequest(level="info")

        # Act
        await self.session.send_request(request)

        # Assert
        assert len(self.transport.client_sent_messages) == 1
        sent_message = self.transport.client_sent_messages[0]
        assert sent_message.payload["method"] == "logging/setLevel"

    async def test_returns_result_response(self, mock_ensure_initialized, monkeypatch):
        """Returns the server's result response."""

        # Arrange
        def numbered_ids():
            return iter(f"test-id-{i}" for i in range(1, 100))

        id_generator = numbered_ids()
        monkeypatch.setattr(
            "conduit.client.session.uuid.uuid4", lambda: next(id_generator)
        )

        request = PingRequest()

        # Act
        async def send_and_respond():
            task = asyncio.create_task(self.session.send_request(request))
            await self.wait_for_sent_message("ping")

            # Send result response
            self.server.send_message(
                {"jsonrpc": "2.0", "id": "test-id-1", "result": {}}
            )

            return await task

        result = await send_and_respond()

        # Assert
        assert result is not None
        assert isinstance(result, Result)

    async def test_returns_error_response(self, mock_ensure_initialized, monkeypatch):
        """Returns the server's error response."""

        # Arrange
        def numbered_ids():
            return iter(f"test-id-{i}" for i in range(1, 100))

        id_generator = numbered_ids()
        monkeypatch.setattr(
            "conduit.client.session.uuid.uuid4", lambda: next(id_generator)
        )

        request = PingRequest()

        # Act
        async def send_and_respond():
            task = asyncio.create_task(self.session.send_request(request))
            await self.wait_for_sent_message("ping")

            # Send error response
            self.server.send_message(
                {
                    "jsonrpc": "2.0",
                    "id": "test-id-1",
                    "error": {"code": -32600, "message": "Invalid request"},
                }
            )

            return await task

        result = await send_and_respond()

        # Assert
        assert result is not None  # Should be an Error object, not raise
        assert isinstance(result, Error)

    async def test_raises_timeout_error_and_sends_cancellation(
        self, mock_ensure_initialized, monkeypatch
    ):
        """Raises TimeoutError and sends cancellation notification on timeout."""

        # Arrange
        def numbered_ids():
            return iter(f"test-id-{i}" for i in range(1, 100))

        id_generator = numbered_ids()
        monkeypatch.setattr(
            "conduit.client.session.uuid.uuid4", lambda: next(id_generator)
        )

        request = PingRequest()

        # Act & Assert
        with pytest.raises(
            TimeoutError, match="Request test-id-1 timed out after 0.1s"
        ):
            await self.session.send_request(request, timeout=0.1)  # Short timeout

        # Assert cancellation notification was sent
        await self.wait_for_sent_message("notifications/cancelled")

        # Find the cancellation message
        cancellation_msg = None
        for msg in self.transport.client_sent_messages:
            if msg.payload.get("method") == "notifications/cancelled":
                cancellation_msg = msg
                break

        assert cancellation_msg is not None
        assert cancellation_msg.payload["params"]["requestId"] == "test-id-1"
        assert "timed out" in cancellation_msg.payload["params"]["reason"]

    async def test_removes_from_pending_dict_on_success(self, monkeypatch):
        """Removes request from pending dict after successful response."""

        # Arrange
        def numbered_ids():
            return iter(f"test-id-{i}" for i in range(1, 100))

        id_generator = numbered_ids()
        monkeypatch.setattr(
            "conduit.client.session.uuid.uuid4", lambda: next(id_generator)
        )

        request = PingRequest()
        await self.session._start()

        # Act
        async def send_ping_and_respond():
            task = asyncio.create_task(self.session.send_request(request))
            await self.wait_for_sent_message("ping")

            # Verify it's in pending dict
            assert "test-id-1" in self.session._pending_requests

            # Send response
            self.server.send_message(
                {"jsonrpc": "2.0", "id": "test-id-1", "result": {}}
            )

            return await task

        await send_ping_and_respond()

        # Assert - cleaned up from pending dict
        assert "test-id-1" not in self.session._pending_requests

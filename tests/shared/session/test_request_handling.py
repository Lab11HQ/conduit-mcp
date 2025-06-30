import asyncio
from unittest.mock import AsyncMock

import pytest

from conduit.protocol.base import INTERNAL_ERROR
from conduit.protocol.common import EmptyResult

from .conftest import BaseSessionTest


class TestRequestHandling(BaseSessionTest):
    _default_yield_time = 0.01

    async def test_calls_session_request_handler_with_payload(self):
        """_handle_request calls _handle_session_request with the correct payload."""
        # Arrange
        mock_handler = AsyncMock(return_value=EmptyResult())
        self.session._handle_session_request = mock_handler

        request_payload = {"jsonrpc": "2.0", "id": "test-123", "method": "ping"}

        # Act
        await self.session._handle_request(request_payload)

        # Assert - handler was called with correct payload
        mock_handler.assert_awaited_once_with(request_payload)

    async def test_sends_result_response_for_successful_handler(self):
        """Successful handler results are sent as JSON-RPC result responses."""
        # Arrange
        mock_handler = AsyncMock(return_value=EmptyResult())
        self.session._handle_session_request = mock_handler

        request_payload = {"jsonrpc": "2.0", "id": "test-456", "method": "test"}

        # Act
        await self.session._handle_request(request_payload)

        # Assert - proper result response sent
        assert len(self.transport.sent_messages) == 1
        sent_message = self.transport.sent_messages[0]

        assert sent_message["jsonrpc"] == "2.0"
        assert sent_message["id"] == "test-456"
        assert "result" in sent_message
        assert "error" not in sent_message
        assert sent_message["result"] == {}

    async def test_sends_internal_error_for_handler_exception(self):
        """Handler exceptions are caught and sent as INTERNAL_ERROR responses."""
        # Arrange
        mock_handler = AsyncMock(side_effect=ValueError("Something went wrong"))
        self.session._handle_session_request = mock_handler

        request_payload = {"jsonrpc": "2.0", "id": "test-789", "method": "failing"}

        # Act
        await self.session._handle_request(request_payload)

        # Assert - handler was called
        mock_handler.assert_awaited_once_with(request_payload)

        # Assert - error response sent
        assert len(self.transport.sent_messages) == 1
        sent_message = self.transport.sent_messages[0]

        assert sent_message["jsonrpc"] == "2.0"
        assert sent_message["id"] == "test-789"
        assert "error" in sent_message
        assert "result" not in sent_message

        # Assert - proper error details
        error = sent_message["error"]
        assert error["code"] == INTERNAL_ERROR
        assert "Internal error processing request test-789" in error["message"]

    async def test_sends_cancellation_error_when_handler_cancelled(self):
        """Cancelled request handlers send INTERNAL_ERROR cancellation responses."""

        # Arrange
        async def cancelled_handler(payload):
            # Simulate the handler being cancelled mid-execution
            raise asyncio.CancelledError()

        self.session._handle_session_request = cancelled_handler
        request_payload = {"jsonrpc": "2.0", "id": "test-cancelled", "method": "slow"}

        # Act
        await self.session._handle_request(request_payload)

        # Assert - cancellation error response sent
        assert len(self.transport.sent_messages) == 1
        sent_message = self.transport.sent_messages[0]

        assert sent_message["jsonrpc"] == "2.0"
        assert sent_message["id"] == "test-cancelled"
        assert "error" in sent_message

        error = sent_message["error"]
        assert error["code"] == INTERNAL_ERROR
        assert "cancelled" in error["message"].lower()

    async def test_transport_failures_bubble_up(self):
        """Transport send failures are not caught and bubble up to caller."""
        # Arrange
        mock_handler = AsyncMock(return_value=EmptyResult())
        self.session._handle_session_request = mock_handler

        # Mock transport to fail on send
        async def failing_send(payload):
            raise ConnectionError("Network down")

        self.transport.send = failing_send
        request_payload = {"jsonrpc": "2.0", "id": "test-transport", "method": "test"}

        # Act & Assert - transport error bubbles up
        with pytest.raises(ConnectionError, match="Network down"):
            await self.session._handle_request(request_payload)

        # Assert - handler was still called (we got to the send step)
        mock_handler.assert_awaited_once_with(request_payload)

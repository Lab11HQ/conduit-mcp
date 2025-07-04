import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from conduit.protocol.base import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    Error,
)
from conduit.protocol.common import EmptyResult, PingRequest

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
        mock_handler.assert_awaited_once_with(PingRequest())

    async def test_sends_result_response_for_successful_handler(self):
        """Successful handler results are sent as JSON-RPC result responses."""
        # Arrange
        mock_handler = AsyncMock(return_value=EmptyResult())
        self.session._handle_session_request = mock_handler

        request_payload = {"jsonrpc": "2.0", "id": "test-456", "method": "ping"}

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

        request_payload = {"jsonrpc": "2.0", "id": "test-789", "method": "ping"}

        # Act
        await self.session._handle_request(request_payload)

        # Assert - handler was called
        mock_handler.assert_awaited_once_with(PingRequest())

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
        request_payload = {"jsonrpc": "2.0", "id": "test-cancelled", "method": "ping"}

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
        request_payload = {"jsonrpc": "2.0", "id": "test-transport", "method": "ping"}

        # Act & Assert - transport error bubbles up
        with pytest.raises(ConnectionError, match="Network down"):
            await self.session._handle_request(request_payload)

        # Assert - handler was still called (we got to the send step)
        mock_handler.assert_awaited_once_with(PingRequest())

    async def test_handle_request_sends_parse_error_directly(self):
        # Arrange - mock _parse_request to return an error
        parse_error = Error(
            code=METHOD_NOT_FOUND, message="Unknown method: test/method"
        )
        self.session._parse_request = Mock(return_value=parse_error)

        # Mock the session handler to ensure it's NOT called
        mock_handler = AsyncMock()
        self.session._handle_session_request = mock_handler

        request_payload = {
            "jsonrpc": "2.0",
            "id": "test-parse-error",
            "method": "test/method",
        }

        # Act
        await self.session._handle_request(request_payload)

        # Assert - parsing error was sent directly
        assert len(self.transport.sent_messages) == 1
        sent_message = self.transport.sent_messages[0]

        assert sent_message["id"] == "test-parse-error"
        assert "error" in sent_message
        assert sent_message["error"]["code"] == METHOD_NOT_FOUND
        assert sent_message["error"]["message"] == "Unknown method: test/method"

        # Assert - session handler was NOT called
        mock_handler.assert_not_called()

    async def test_handle_request_calls_session_handler_with_parsed_request(self):
        # Arrange - mock _parse_request to return a valid request
        parsed_request = PingRequest()
        self.session._parse_request = Mock(return_value=parsed_request)

        # Mock the session handler to return a result
        mock_handler = AsyncMock(return_value=EmptyResult())
        self.session._handle_session_request = mock_handler

        request_payload = {"jsonrpc": "2.0", "id": "test-parsed", "method": "ping"}

        # Act
        await self.session._handle_request(request_payload)

        # Assert - session handler was called with parsed request
        mock_handler.assert_awaited_once_with(parsed_request)

        # Assert - successful response was sent
        assert len(self.transport.sent_messages) == 1
        sent_message = self.transport.sent_messages[0]
        assert sent_message["jsonrpc"] == "2.0"
        assert sent_message["id"] == "test-parsed"
        assert "result" in sent_message


class TestParseRequest(BaseSessionTest):
    """Test the _parse_request method in isolation."""

    def test_parse_request_returns_typed_request_for_valid_payload(self):
        """_parse_request returns a typed Request object for valid payloads."""
        # Arrange
        payload = {"jsonrpc": "2.0", "id": "test-123", "method": "ping", "params": {}}

        # Act
        result = self.session._parse_request(payload)

        # Assert
        assert isinstance(result, PingRequest)
        assert result.method == "ping"

    def test_parse_request_returns_method_not_found_error_for_unknown_method(self):
        """_parse_request returns METHOD_NOT_FOUND error for unknown methods."""
        # Arrange
        payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "unknown/method",
            "params": {},
        }

        # Act
        result = self.session._parse_request(payload)

        # Assert
        assert isinstance(result, Error)
        assert result.code == METHOD_NOT_FOUND
        assert "Unknown method: unknown/method" in result.message

    def test_parse_request_returns_invalid_params_error_for_missing_required_fields(
        self,
    ):
        """_parse_request returns INVALID_PARAMS error for missing required fields."""
        # Arrange - initialize request missing clientInfo
        payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                # Missing clientInfo
            },
        }

        # Act
        result = self.session._parse_request(payload)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INVALID_PARAMS
        assert "Failed to deserialize initialize request" in result.message
        assert result.data["method"] == "initialize"

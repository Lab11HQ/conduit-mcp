import asyncio

from conduit.protocol.base import INTERNAL_ERROR, Error
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.tools import ListToolsRequest

from .conftest import BaseSessionTest


class TestResponseHandling(BaseSessionTest):
    _default_yield_time = 0.01

    """Test the _handle_response method."""

    async def test_resolves_pending_request_with_result(self):
        """Success responses resolve pending requests with Result objects."""
        # Arrange
        request = PingRequest()
        future = asyncio.Future()
        self.session._pending_requests["test-123"] = (request, future)

        response_payload = {"jsonrpc": "2.0", "id": "test-123", "result": {}}

        # Act
        await self.session._handle_response(response_payload)

        # Assert
        assert future.done()
        result = future.result()
        assert isinstance(result, EmptyResult)

    async def test_resolves_pending_request_with_error(self):
        """Error responses resolve pending requests with Error objects."""
        # Arrange
        request = PingRequest()
        future = asyncio.Future()
        self.session._pending_requests["test-456"] = (request, future)

        response_payload = {
            "jsonrpc": "2.0",
            "id": "test-456",
            "error": {"code": -1, "message": "Something went wrong"},
        }

        # Act
        await self.session._handle_response(response_payload)

        # Assert
        assert future.done()
        result = future.result()
        assert isinstance(result, Error)
        assert result.code == -1
        assert result.message == "Something went wrong"

    async def test_ignores_unmatched_responses(self):
        """Responses without matching pending requests are logged and ignored."""
        # Arrange
        response_payload = {"jsonrpc": "2.0", "id": "unknown-request", "result": {}}

        # Act - should not raise
        await self.session._handle_response(response_payload)

        # Assert
        assert len(self.session._pending_requests) == 0

    async def test_cleans_up_pending_request(self):
        """Pending requests are removed when responses are processed."""
        # Arrange
        request = PingRequest()
        future = asyncio.Future()
        self.session._pending_requests["cleanup-test"] = (request, future)

        response_payload = {"jsonrpc": "2.0", "id": "cleanup-test", "result": {}}

        # Act
        await self.session._handle_response(response_payload)

        # Assert
        assert "cleanup-test" not in self.session._pending_requests
        assert future.done()


class TestParseResponse(BaseSessionTest):
    async def test_parses_result_response_into_result_object(self):
        """Successfully parses result response for PingRequest into EmptyResult."""
        # Arrange
        request = PingRequest()
        response_payload = {"jsonrpc": "2.0", "id": "test-123", "result": {}}

        # Act
        result = self.session._parse_response(response_payload, request)

        # Assert
        assert isinstance(result, EmptyResult)
        assert not isinstance(result, Error)

    async def test_parses_error_response_into_error_object(self):
        """Successfully parses error response for ListToolsRequest into Error object."""
        # Arrange
        request = ListToolsRequest()
        response_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "error": {
                "code": -32601,
                "message": "Method not found",
                "data": {"additional": "info"},
            },
        }

        # Act
        result = self.session._parse_response(response_payload, request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == -32601
        assert result.message == "Method not found"
        assert result.data == {"additional": "info"}

    async def test_returns_error_when_result_parsing_fails(self):
        """Returns Error when result parsing fails for ListToolsRequest."""
        # Arrange
        request = ListToolsRequest()
        response_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "result": {
                "tools": "invalid_format"  # Should be a list, not a string
            },
        }

        # Act
        result = self.session._parse_response(response_payload, request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert "Failed to parse ListToolsResult response" in result.message
        assert result.data["expected_type"] == "ListToolsResult"
        assert result.data["full_response"] == response_payload
        assert "parse_error" in result.data
        assert "error_type" in result.data

    async def test_returns_error_when_error_parsing_fails(self):
        """Returns Error when error parsing fails for ListToolsRequest."""
        # Arrange
        request = ListToolsRequest()
        response_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            "error": "invalid_error_format",  # Should be an object, not a string
        }

        # Act
        result = self.session._parse_response(response_payload, request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert result.message == "Failed to parse response"
        assert result.data["full_response"] == response_payload
        assert "parse_error" in result.data
        assert "error_type" in result.data

    async def test_returns_error_when_response_has_neither_result_nor_error(self):
        """Returns Error when response has neither result nor error field."""
        # Arrange
        request = ListToolsRequest()
        response_payload = {
            "jsonrpc": "2.0",
            "id": "test-123",
            # Missing both "result" and "error"
        }

        # Act
        result = self.session._parse_response(response_payload, request)

        # Assert
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert result.message == "Failed to parse response"
        assert result.data["full_response"] == response_payload
        assert "parse_error" in result.data
        assert "error_type" in result.data

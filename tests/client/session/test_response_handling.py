import asyncio

import pytest

from conduit.protocol.base import Error
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.logging import SetLevelRequest
from conduit.protocol.tools import CallToolRequest

from .conftest import BaseSessionTest


class TestResponseHandler(BaseSessionTest):
    async def test_resolves_successful_response_future(self):
        # Arrange
        request_id = "42"
        future = asyncio.Future()
        self.session._pending_requests[request_id] = (PingRequest, future)

        # Create the expected payload
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {},
        }

        # Act
        await self.session._handle_response(response)

        # Assert
        assert future.done()
        result = future.result()
        assert isinstance(result, EmptyResult)
        assert result == EmptyResult()

    async def test_resolves_error_response_future(self):
        # Arrange
        request_id = "123"
        future = asyncio.Future()
        self.session._pending_requests[request_id] = (CallToolRequest, future)

        # Create the expected payload
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Method not found"},
        }

        # Act
        await self.session._handle_response(response)

        # Assert
        assert future.done()
        result = future.result()
        assert isinstance(result, Error)

    async def test_handles_unmatched_response_gracefully(self):
        # Arrange
        unmatched_id = "999"
        unmatched_payload = {
            "jsonrpc": "2.0",
            "id": unmatched_id,
            "result": {"data": "no matching request"},
        }

        # Ensure no pending request exists for this ID
        assert unmatched_id not in self.session._pending_requests

        # Act
        await self.session._handle_response(unmatched_payload)

        # Assert
        # Should complete without error and not create any futures
        assert unmatched_id not in self.session._pending_requests
        assert len(self.session._pending_requests) == 0

    async def test_matches_response_to_correct_request_by_id(self):
        # Arrange - two different pending requests
        future_100 = asyncio.Future()
        future_200 = asyncio.Future()
        self.session._pending_requests["100"] = (PingRequest(), future_100)
        self.session._pending_requests["200"] = (PingRequest(), future_200)

        # Act - respond to just the second one
        response = {
            "jsonrpc": "2.0",
            "id": "200",
            "result": {},
        }
        await self.session._handle_response(response)

        # Assert - only the matching future is resolved
        assert not future_100.done()
        assert future_200.done()

        # Clean up
        future_100.cancel()

    async def test_raises_when_request_missing_result_type(self):
        """Test error handling when a request without result type gets a response.

        This should never happen in normal operation - requests that don't expect
        responses (like SetLevelRequest) should not be added to _pending_requests
        in the first place. This test verifies we catch this programming error
        with a clear exception rather than silently corrupting state.
        """
        # Arrange - simulate the bug: a no-response request in pending_requests
        request_id = "42"
        future = asyncio.Future()
        set_level_request = SetLevelRequest(level="info")
        self.session._pending_requests[request_id] = (set_level_request, future)

        response = {"jsonrpc": "2.0", "id": request_id, "result": {}}

        # Act & Assert
        with pytest.raises(
            ValueError, match="SetLevelRequest.*missing expected_result_type"
        ):
            await self.session._handle_response(response)


class TestResponseValidator(BaseSessionTest):
    def test_is_valid_response_identifies_success_responses(self):
        # Arrange
        valid_response = {"jsonrpc": "2.0", "id": "42", "result": {"data": "success"}}

        # Act & Assert
        assert self.session._is_valid_response(valid_response) is True

    def test_is_valid_response_identifies_error_responses(self):
        # Arrange
        valid_error_response = {
            "jsonrpc": "2.0",
            "id": "123",
            "error": {"code": -32601, "message": "Method not found"},
        }

        # Act & Assert
        assert self.session._is_valid_response(valid_error_response) is True

    def test_is_valid_response_rejects_both_result_and_error(self):
        # Arrange
        invalid_response = {
            "jsonrpc": "2.0",
            "id": "42",
            "result": {"data": "success"},
            "error": {"code": -1, "message": "Also an error"},  # Invalid per spec
        }

        # Act & Assert
        assert self.session._is_valid_response(invalid_response) is False

    def test_is_valid_response_accepts_string_ids(self):
        # Arrange
        response_with_string_id = {"jsonrpc": "2.0", "id": "abc-123", "result": {}}

        # Act & Assert
        assert self.session._is_valid_response(response_with_string_id) is True

    def test_is_valid_response_rejects_missing_id(self):
        # Arrange
        response_without_id = {"jsonrpc": "2.0", "result": {"data": "success"}}

        # Act & Assert
        assert self.session._is_valid_response(response_without_id) is False

    def test_is_valid_response_rejects_non_int_or_string_ids(self):
        # Arrange
        response_with_float_id = {"jsonrpc": "2.0", "id": 1.9, "result": {}}
        response_with_list_id = {"jsonrpc": "2.0", "id": [1, 2, 3], "result": {}}

        # Act & Assert
        assert self.session._is_valid_response(response_with_float_id) is False
        assert self.session._is_valid_response(response_with_list_id) is False

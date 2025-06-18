import asyncio

from conduit.protocol.base import Error
from conduit.protocol.common import EmptyResult, PingRequest

from .conftest import BaseSessionTest


class TestResponseHandler(BaseSessionTest):
    async def test_resolves_successful_response_future(self):
        # Arrange
        request_id = 42
        expected_payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {},
        }
        expected_metadata = {"transport": "test"}

        # Create and store a pending future
        future = asyncio.Future()
        self.session._pending_requests[request_id] = (PingRequest(), future)

        # Act
        await self.session._handle_response(expected_payload, expected_metadata)

        # Assert
        assert future.done()
        result = future.result()
        assert result == EmptyResult()

    async def test_resolves_error_response_future(self):
        # Arrange
        request_id = 123
        expected_payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Method not found"},
        }

        # Create and store a pending future
        future = asyncio.Future()
        self.session._pending_requests[request_id] = (PingRequest(), future)

        # Act
        await self.session._handle_response(expected_payload, None)

        # Assert
        assert future.done()
        result = future.result()
        assert isinstance(result, Error)

    async def test_handles_unmatched_response_gracefully(self):
        # Arrange
        unmatched_id = 999
        unmatched_payload = {
            "jsonrpc": "2.0",
            "id": unmatched_id,
            "result": {"data": "no matching request"},
        }
        metadata = {"transport": "test"}

        # Ensure no pending request exists for this ID
        assert unmatched_id not in self.session._pending_requests

        # Act
        await self.session._handle_response(unmatched_payload, metadata)

        # Assert
        # Should complete without error and not create any futures
        assert unmatched_id not in self.session._pending_requests
        assert len(self.session._pending_requests) == 0

    async def test_resolves_multiple_responses_with_correct_id_matching(self):
        # Arrange
        futures = {}

        for request_id in [100, 200]:
            future = asyncio.Future()
            futures[request_id] = future
            self.session._pending_requests[request_id] = (PingRequest(), future)

        # Create responses for each request
        responses = [
            (
                {"jsonrpc": "2.0", "id": 100, "result": {}},
                {"meta": "first"},
            ),
            (
                {
                    "jsonrpc": "2.0",
                    "id": 200,
                    "error": {"code": -1, "message": "second"},
                },
                {"meta": "second"},
            ),
        ]

        # Act
        for payload, metadata in responses:
            await self.session._handle_response(payload, metadata)

        # Assert
        assert futures[100].done()
        assert futures[200].done()
        assert futures[100].result() == EmptyResult()
        assert isinstance(futures[200].result(), Error)


class TestResponseValidator(BaseSessionTest):
    def test_is_valid_response_identifies_success_responses(self):
        # Arrange
        valid_response = {"jsonrpc": "2.0", "id": 42, "result": {"data": "success"}}

        # Act & Assert
        assert self.session._is_valid_response(valid_response) is True

    def test_is_valid_response_identifies_error_responses(self):
        # Arrange
        valid_error_response = {
            "jsonrpc": "2.0",
            "id": 123,
            "error": {"code": -32601, "message": "Method not found"},
        }

        # Act & Assert
        assert self.session._is_valid_response(valid_error_response) is True

    def test_is_valid_response_rejects_both_result_and_error(self):
        # Arrange
        invalid_response = {
            "jsonrpc": "2.0",
            "id": 42,
            "result": {"data": "success"},
            "error": {"code": -1, "message": "Also an error"},  # Invalid per spec
        }

        # Act & Assert
        assert self.session._is_valid_response(invalid_response) is False

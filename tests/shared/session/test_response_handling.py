import asyncio

from conduit.protocol.base import Error
from conduit.protocol.common import EmptyResult, PingRequest

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

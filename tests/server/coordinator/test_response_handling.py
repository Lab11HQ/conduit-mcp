import asyncio

from conduit.protocol.base import Error, Result
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.roots import ListRootsRequest


class TestResponseHandling:
    async def test_resolves_pending_request_with_result(
        self, coordinator, client_manager, yield_loop
    ):
        """Test that successful responses are parsed and resolved correctly."""
        # Arrange
        await coordinator.start()
        client_id = "test_client"
        request_id = "test-request-123"

        # Set up a pending request
        original_request = PingRequest()
        future: asyncio.Future[Result | Error] = asyncio.Future()

        client_manager.register_client(client_id)
        client_manager.track_request_to_client(
            client_id, request_id, original_request, future
        )

        # Create a successful response payload
        response_payload = {"jsonrpc": "2.0", "id": request_id, "result": {}}

        # Act
        await coordinator._handle_response(client_id, response_payload)
        await yield_loop()

        # Assert
        assert future.done()
        result = future.result()
        assert isinstance(result, EmptyResult)

        # Verify the request was cleaned up
        assert client_manager.get_request_to_client(client_id, request_id) is None

    async def test_resolves_pending_request_with_error(
        self, coordinator, client_manager, yield_loop
    ):
        """Test that error responses are parsed and resolved correctly."""
        # Arrange
        await coordinator.start()
        client_id = "test_client"
        request_id = "test-request-456"

        # Set up a pending request
        original_request = ListRootsRequest()
        future: asyncio.Future[Result | Error] = asyncio.Future()

        client_manager.register_client(client_id)
        client_manager.track_request_to_client(
            client_id, request_id, original_request, future
        )

        # Create an error response payload
        error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": "Method not found",
                "data": {"details": "Unknown method"},
            },
        }

        # Act
        await coordinator._handle_response(client_id, error_response)
        await yield_loop()

        # Assert
        assert future.done()
        result = future.result()
        assert isinstance(result, Error)
        assert result.code == -32601

        # Verify the request was cleaned up
        assert client_manager.get_request_to_client(client_id, request_id) is None

    async def test_ignores_response_for_unknown_client(self, coordinator):
        """Test that responses from unknown clients are ignored gracefully."""
        # Arrange
        await coordinator.start()
        unknown_client_id = "unknown_client"
        request_id = "test-request-789"

        # Create response payload
        response_payload = {"jsonrpc": "2.0", "id": request_id, "result": {}}

        # Act & Assert - should handle gracefully without raising
        await coordinator._handle_response(unknown_client_id, response_payload)
        # If we get here, the test passed

    async def test_ignores_response_for_unknown_request(
        self, coordinator, client_manager
    ):
        """Test that responses for unknown requests are ignored gracefully."""
        # Arrange
        await coordinator.start()
        client_id = "test_client"
        unknown_request_id = "unknown-request-999"

        # Register client but don't track any requests
        client_manager.register_client(client_id)

        # Create response payload
        response_payload = {"jsonrpc": "2.0", "id": unknown_request_id, "result": {}}

        # Act & Assert - should handle gracefully without raising
        await coordinator._handle_response(client_id, response_payload)
        # If we get here, the test passed

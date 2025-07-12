import asyncio

from conduit.protocol.common import PingRequest


class TestCancelAPI:
    """Test the public cancellation API methods."""

    async def test_cancel_request_from_client_success(
        self, coordinator, client_manager, yield_loop
    ):
        """Test successfully cancelling a specific request from a client."""
        # Arrange: Set up a client with a tracked request
        client_id = "test-client"
        request_id = "req-123"
        mock_request = PingRequest()

        # Register client and create a mock task
        client_manager.register_client(client_id)
        mock_task = asyncio.create_task(asyncio.sleep(10))
        client_manager.track_request_from_client(
            client_id, request_id, mock_request, mock_task
        )

        # Verify task is tracked
        assert client_manager.get_request_from_client(client_id, request_id) == (
            mock_request,
            mock_task,
        )

        # Act: Cancel the specific request
        result = await coordinator.cancel_request_from_client(client_id, request_id)

        # Assert: Request was found and successfully cancelled
        assert result is True
        await yield_loop()
        try:
            await mock_task
        except asyncio.CancelledError:
            pass
        assert mock_task.cancelled()

        # Assert: Request was removed from tracking
        assert client_manager.get_request_from_client(client_id, request_id) is None

    async def test_cancel_request_from_client_not_found(
        self, coordinator, client_manager
    ):
        """Test cancelling request that doesn't exist returns False."""
        # Arrange: Set up a client with no requests
        client_id = "test-client"
        client_manager.register_client(client_id)

        # Act: Try to cancel nonexistent request
        result = await coordinator.cancel_request_from_client(
            client_id, "nonexistent-req"
        )

        # Assert: Returns False
        assert result is False

    async def test_cancel_request_from_client_already_completed(
        self, coordinator, client_manager, yield_loop
    ):
        """Test cancelling already completed request returns False."""
        # Arrange: Set up a client with a completed task
        client_id = "test-client"
        request_id = "req-123"
        mock_request = PingRequest()
        client_manager.register_client(client_id)

        # Create a task that completes immediately
        mock_task = asyncio.create_task(asyncio.sleep(0))
        client_manager.track_request_from_client(
            client_id, request_id, mock_request, mock_task
        )

        # Wait for task to complete
        await yield_loop()
        assert mock_task.done()

        # Act: Try to cancel the already completed request
        result = await coordinator.cancel_request_from_client(client_id, request_id)

        # Assert: Returns False (task was found but couldn't be cancelled)
        assert result is False

        # Assert: Request was still removed from tracking
        assert client_manager.get_request_from_client(client_id, request_id) is None

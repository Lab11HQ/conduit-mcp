import asyncio

from conduit.protocol.base import INTERNAL_ERROR, Error
from conduit.protocol.common import PingRequest
from conduit.server.client_manager import ClientManager


class TestClientLifecycle:
    def test_register_and_retrieve_client_with_default_state(self):
        """Test basic client registration and retrieval flow."""
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"

        # Act
        context = manager.register_client(client_id)
        retrieved_context = manager.get_client(client_id)

        # Assert
        assert context is not None
        assert context.id == client_id
        assert context.initialized is False
        assert context.capabilities is None
        assert context.info is None
        assert context.protocol_version is None
        assert context.roots is None
        assert context.log_level is None
        assert len(context.subscriptions) == 0
        assert len(context.requests_from_client) == 0
        assert len(context.requests_to_client) == 0

        # Verify retrieval returns same context
        assert retrieved_context is context
        assert manager.client_count() == 1
        assert manager.is_client_initialized(client_id) is False

    async def test_disconnect_client_with_active_or_pending_requests(self):
        """Test client disconnection properly cleans up active requests."""
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"
        context = manager.register_client(client_id)

        # Mock an in-flight request from the client
        processing_client_request = asyncio.create_task(asyncio.sleep(10))
        manager.track_request_from_client(client_id, "req-1", processing_client_request)

        # Mock a pending request to the client
        awaiting_client_response = asyncio.Future()
        ping_request = PingRequest()
        manager.track_request_to_client(
            client_id, "req-2", ping_request, awaiting_client_response
        )

        # Verify setup
        assert len(context.requests_from_client) == 1
        assert len(context.requests_to_client) == 1
        assert not processing_client_request.cancelled()
        assert not awaiting_client_response.done()

        # Act
        manager.disconnect_client(client_id)

        # Wait for cancellation to complete
        try:
            await processing_client_request
        except asyncio.CancelledError:
            pass  # Expected cancellation

        # Assert - client is removed
        assert manager.get_client(client_id) is None
        assert manager.client_count() == 0

        # Assert - in-flight task is cancelled
        assert processing_client_request.cancelled()

        # Assert - pending future is resolved with error
        assert awaiting_client_response.done()
        result = awaiting_client_response.result()
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR
        assert "Client disconnected" in result.message

    async def test_cleans_up_all_clients_with_active_or_pending_requests(self):
        """Test cleanup_all_clients handles multiple clients with active requests."""
        # Arrange
        manager = ClientManager()

        # Register multiple clients with different states
        client1_id = "client-1"
        client2_id = "client-2"
        client3_id = "client-3"

        context1 = manager.register_client(client1_id)
        context2 = manager.register_client(client2_id)
        context3 = manager.register_client(client3_id)

        # Client 1: Has both inbound and outbound requests
        processing_request_1 = asyncio.create_task(asyncio.sleep(10))
        awaiting_response_1 = asyncio.Future()
        manager.track_request_from_client(client1_id, "req-1", processing_request_1)
        manager.track_request_to_client(
            client1_id, "req-2", PingRequest(), awaiting_response_1
        )

        # Client 2: Only has outbound request
        awaiting_response_2 = asyncio.Future()
        manager.track_request_to_client(
            client2_id, "req-3", PingRequest(), awaiting_response_2
        )

        # Client 3: Only has inbound request
        processing_request_3 = asyncio.create_task(asyncio.sleep(10))
        manager.track_request_from_client(client3_id, "req-4", processing_request_3)

        # Verify setup
        assert manager.client_count() == 3

        # Act
        manager.cleanup_all_clients()

        # Wait for all cancellations to complete
        for task in [processing_request_1, processing_request_3]:
            try:
                await task
            except asyncio.CancelledError:
                pass  # Expected cancellation

        # Assert - all clients removed
        assert manager.client_count() == 0
        assert manager.get_client(client1_id) is None
        assert manager.get_client(client2_id) is None
        assert manager.get_client(client3_id) is None

        # Assert - all tasks cancelled
        assert processing_request_1.cancelled()
        assert processing_request_3.cancelled()

        # Assert - all pending futures resolved with errors
        assert awaiting_response_1.done()
        assert awaiting_response_2.done()

        for future in [awaiting_response_1, awaiting_response_2]:
            result = future.result()
            assert isinstance(result, Error)
            assert result.code == INTERNAL_ERROR
            assert "Client disconnected" in result.message

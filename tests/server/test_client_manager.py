import asyncio

import pytest

from conduit.protocol.base import INTERNAL_ERROR, Error, Result
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.server.client_manager import ClientManager


class TestClientLifecycle:
    def test_register_and_retrieve_client_with_default_state(self):
        """Test basic client registration and retrieval flow."""
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"

        # Act
        state = manager.register_client(client_id)
        retrieved_state = manager.get_client(client_id)

        # Assert
        assert state is not None
        assert state.id == client_id
        assert state.initialized is False
        assert state.capabilities is None
        assert state.info is None
        assert state.protocol_version is None
        assert state.roots is None
        assert state.log_level is None
        assert len(state.subscriptions) == 0
        assert len(state.requests_from_client) == 0
        assert len(state.requests_to_client) == 0

        # Verify retrieval returns same state
        assert retrieved_state is state
        assert manager.client_count() == 1
        assert manager.is_protocol_initialized(client_id) is False

    async def test_cleanup_client_with_active_or_pending_requests(self):
        """Test client cleanup properly cleans up active requests."""
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"
        state = manager.register_client(client_id)

        # Mock an in-flight request from the client
        processing_client_request = asyncio.create_task(asyncio.sleep(10))
        manager.track_request_from_client(
            client_id, "req-1", PingRequest(), processing_client_request
        )

        # Mock a pending request to the client
        awaiting_client_response = asyncio.Future()
        ping_request = PingRequest()
        manager.track_request_to_client(
            client_id, "req-2", ping_request, awaiting_client_response
        )

        # Verify setup
        assert len(state.requests_from_client) == 1
        assert len(state.requests_to_client) == 1
        assert not processing_client_request.cancelled()
        assert not awaiting_client_response.done()

        # Act
        manager.cleanup_client(client_id)

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

        state1 = manager.register_client(client1_id)
        state2 = manager.register_client(client2_id)
        state3 = manager.register_client(client3_id)

        # Client 1: Has both inbound and outbound requests
        processing_request_1 = asyncio.create_task(asyncio.sleep(10))
        awaiting_response_1 = asyncio.Future()
        manager.track_request_from_client(
            client1_id, "req-1", PingRequest(), processing_request_1
        )
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
        manager.track_request_from_client(
            client3_id, "req-4", PingRequest(), processing_request_3
        )

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


class TestOutboundRequests:
    async def test_track_request_to_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"
        request_id = "req-123"

        manager.register_client(client_id)

        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        # Act
        manager.track_request_to_client(client_id, request_id, request, future)

        # Assert
        client_state = manager.get_client(client_id)
        assert client_state is not None

        tracked_request, tracked_future = client_state.requests_to_client[request_id]
        assert tracked_request is request
        assert tracked_future is future

    async def test_track_request_to_client_raises_for_unregistered_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "nonexistent-client"
        request_id = "req-123"

        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        # Act & Assert
        with pytest.raises(ValueError):
            manager.track_request_to_client(client_id, request_id, request, future)

    async def test_untrack_request_to_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"
        request_id = "req-123"

        manager.register_client(client_id)

        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        # Track first, then untrack
        manager.track_request_to_client(client_id, request_id, request, future)
        assert manager.get_request_to_client(client_id, request_id) is not None

        # Act
        result = manager.untrack_request_to_client(client_id, request_id)

        # Assert
        assert result is not None
        untracked_request, untracked_future = result
        assert untracked_request is request
        assert untracked_future is future

        # Verify it's actually removed from tracking
        client_state = manager.get_client(client_id)
        assert request_id not in client_state.requests_to_client

    async def test_untrack_request_to_client_raises_for_unregistered_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "nonexistent-client"
        request_id = "req-123"

        # Act & Assert
        with pytest.raises(ValueError):
            manager.untrack_request_to_client(client_id, request_id)

    async def test_get_request_to_client_returns_none_for_unregistered_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "nonexistent-client"
        request_id = "req-123"

        # Act
        result = manager.get_request_to_client(client_id, request_id)

        # Assert
        assert result is None

    async def test_get_request_to_client_returns_none_for_nonexistent_request(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"
        request_id = "nonexistent-request"

        manager.register_client(client_id)

        # Act
        result = manager.get_request_to_client(client_id, request_id)

        # Assert
        assert result is None

    async def test_resolve_request_to_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"
        request_id = "req-123"

        manager.register_client(client_id)

        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        # Track the request first
        manager.track_request_to_client(client_id, request_id, request, future)

        # Create a result to resolve with
        result = EmptyResult()

        # Act
        manager.resolve_request_to_client(client_id, request_id, result)

        # Assert
        assert future.done()
        assert future.result() is result

        # Verify request is removed from tracking
        client_state = manager.get_client(client_id)
        assert request_id not in client_state.requests_to_client

    async def test_resolve_does_nothing_if_client_not_found(self):
        # Arrange
        manager = ClientManager()
        client_id = "nonexistent-client"
        request_id = "req-123"

        # Verify client doesn't exist
        assert manager.get_client(client_id) is None

        result = EmptyResult()

        # Act & Assert - no error is raised
        manager.resolve_request_to_client(client_id, request_id, result)
        # If we get here without an exception, the test passes

    async def test_resolve_does_nothing_if_request_not_found(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"
        request_id = "nonexistent-request"

        manager.register_client(client_id)

        # Verify request doesn't exist
        assert manager.get_request_to_client(client_id, request_id) is None

        result = EmptyResult()

        # Act & Assert - no error is raised
        manager.resolve_request_to_client(client_id, request_id, result)
        # If we get here without an exception, the test passes

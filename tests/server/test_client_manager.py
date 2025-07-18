import asyncio

import pytest

from conduit.protocol.base import INTERNAL_ERROR, PROTOCOL_VERSION, Error, Result
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.initialization import ClientCapabilities, Implementation
from conduit.server.client_manager import ClientManager, ClientState


class TestRegistration:
    def test_register_and_get_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"

        # Act
        registered_state = manager.register_client(client_id)
        retrieved_state = manager.get_client(client_id)

        # Assert
        assert isinstance(registered_state, ClientState)
        assert retrieved_state is not None
        assert registered_state is retrieved_state
        assert retrieved_state.initialized is False
        assert retrieved_state.capabilities is None

        assert manager.client_count() == 1

    def test_get_does_not_raise_if_client_not_registered(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"

        # Act & Assert
        assert manager.get_client(client_id) is None

    def test_get_ids_returns_list_of_client_ids(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"
        client_id2 = "test-client-2"

        # Act
        manager.register_client(client_id)
        manager.register_client(client_id2)
        id_list = manager.get_client_ids()

        # Assert
        assert len(id_list) == 2
        assert client_id in id_list
        assert client_id2 in id_list

    def test_register_client_twice_overwrites_state(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"

        # Act
        first_state = manager.register_client(client_id)
        second_state = manager.register_client(client_id)
        retrieved_state = manager.get_client(client_id)

        # Assert
        assert first_state is not second_state
        assert retrieved_state is second_state

    def test_initialize_registered_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"
        manager.register_client(client_id)

        capabilities = ClientCapabilities()
        info = Implementation(name="test-client", version="1.0.0")
        protocol_version = PROTOCOL_VERSION

        # Act
        manager.initialize_client(client_id, capabilities, info, protocol_version)
        retrieved_state = manager.get_client(client_id)

        # Assert
        assert retrieved_state is not None
        assert retrieved_state.initialized is True
        assert retrieved_state.capabilities is capabilities
        assert retrieved_state.info is info
        assert retrieved_state.protocol_version == protocol_version

    def test_initialize_unregistered_client_auto_registers(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"
        capabilities = ClientCapabilities()
        info = Implementation(name="test-client", version="1.0.0")
        protocol_version = PROTOCOL_VERSION

        # Act
        manager.initialize_client(client_id, capabilities, info, protocol_version)
        retrieved_state = manager.get_client(client_id)

        # Assert
        assert retrieved_state is not None
        assert retrieved_state.initialized is True
        assert retrieved_state.capabilities is capabilities

    def test_is_protocol_initialized_returns_correct_status(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"

        # Assert - Before registration
        assert not manager.is_protocol_initialized(client_id)

        # Act & Assert - After registration but before initialization
        manager.register_client(client_id)
        assert not manager.is_protocol_initialized(client_id)

        # Act & Assert - After initialization
        capabilities = ClientCapabilities()
        info = Implementation(name="test-client", version="1.0.0")
        manager.initialize_client(client_id, capabilities, info, PROTOCOL_VERSION)
        assert manager.is_protocol_initialized(client_id)


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

    async def test_get_request_to_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"
        request_id = "req-123"

        manager.register_client(client_id)

        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        manager.track_request_to_client(client_id, request_id, request, future)

        # Act
        result = manager.get_request_to_client(client_id, request_id)

        # Assert
        assert result is not None
        retrieved_request, retrieved_future = result
        assert retrieved_request is request

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


class TestInboundRequests:
    async def test_track_request_from_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"
        request_id = "req-123"

        manager.register_client(client_id)

        # Create mock request and task
        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(0))  # Simple task for testing

        # Act
        manager.track_request_from_client(client_id, request_id, request, task)

        # Assert
        client_state = manager.get_client(client_id)
        assert client_state is not None

        tracked_request, tracked_task = client_state.requests_from_client[request_id]
        assert tracked_request is request
        assert tracked_task is task

        # Cleanup
        task.cancel()

    async def test_track_request_from_client_raises_for_unregistered_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "nonexistent-client"
        request_id = "req-123"

        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(0))  # Simple task for testing

        # Act & Assert
        with pytest.raises(ValueError):
            manager.track_request_from_client(client_id, request_id, request, task)

        # Cleanup
        task.cancel()

    async def test_untrack_request_from_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"
        request_id = "req-123"

        manager.register_client(client_id)

        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(0))

        # Track first, then untrack
        manager.track_request_from_client(client_id, request_id, request, task)
        assert manager.get_request_from_client(client_id, request_id) is not None

        # Act
        result = manager.untrack_request_from_client(client_id, request_id)

        # Assert
        assert result is not None
        untracked_request, untracked_task = result
        assert untracked_request is request
        assert untracked_task is task

        # Verify it's actually removed from tracking
        client_state = manager.get_client(client_id)
        assert request_id not in client_state.requests_from_client

        # Cleanup
        task.cancel()

    async def test_untrack_request_from_client_raises_for_unregistered_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "nonexistent-client"
        request_id = "req-123"

        # Act & Assert
        with pytest.raises(ValueError):
            manager.untrack_request_from_client(client_id, request_id)

    async def test_get_request_from_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"
        request_id = "req-123"

        manager.register_client(client_id)

        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(0))

        # Track the request first
        manager.track_request_from_client(client_id, request_id, request, task)

        # Act
        result = manager.get_request_from_client(client_id, request_id)

        # Assert
        assert result is not None
        retrieved_request, retrieved_task = result
        assert retrieved_request is request
        assert retrieved_task is task

        # Cleanup
        task.cancel()

    async def test_get_request_from_client_returns_none_for_unregistered_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "nonexistent-client"
        request_id = "req-123"

        # Act
        result = manager.get_request_from_client(client_id, request_id)

        # Assert
        assert result is None

    async def test_get_request_from_client_returns_none_for_nonexistent_request(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"
        request_id = "nonexistent-request"

        manager.register_client(client_id)

        # Act
        result = manager.get_request_from_client(client_id, request_id)

        # Assert
        assert result is None


class TestCleanup:
    async def test_cleanup_client(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client-123"

        manager.register_client(client_id)

        # Set up inbound request tracking
        inbound_request = PingRequest()
        inbound_task = asyncio.create_task(asyncio.sleep(10))  # Long-running task
        manager.track_request_from_client(
            client_id, "inbound-123", inbound_request, inbound_task
        )

        # Set up outbound request tracking
        outbound_request = PingRequest()
        outbound_future = asyncio.Future[Result | Error]()
        manager.track_request_to_client(
            client_id, "outbound-456", outbound_request, outbound_future
        )

        # Verify setup
        assert manager.get_client(client_id) is not None
        assert not inbound_task.cancelled()
        assert not outbound_future.done()

        # Act
        manager.cleanup_client(client_id)

        # Assert
        # Server should be removed from tracking
        assert manager.get_client(client_id) is None

        # Inbound task should be cancelled
        try:
            await inbound_task
        except asyncio.CancelledError:
            pass
        assert inbound_task.cancelled()

        # Outbound future should be resolved with error
        assert outbound_future.done()
        result = outbound_future.result()
        assert isinstance(result, Error)
        assert result.code == INTERNAL_ERROR

    async def test_cleanup_all_clients(self):
        # Arrange
        manager = ClientManager()
        manager.register_client("client-1")
        manager.register_client("client-2")

        # Act
        manager.cleanup_all_clients()

        # Assert
        assert manager.client_count() == 0
        assert manager.get_client_ids() == []

import asyncio

import pytest

from conduit.client.server_manager import ServerManager, ServerState
from conduit.protocol.base import INTERNAL_ERROR, PROTOCOL_VERSION, Error, Result
from conduit.protocol.common import EmptyResult, PingRequest
from conduit.protocol.initialization import Implementation, ServerCapabilities


class TestRegistration:
    def test_register_and_get_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"

        # Act
        registered_state = manager.register_server(server_id)
        retrieved_state = manager.get_server(server_id)

        # Assert
        assert isinstance(registered_state, ServerState)
        assert retrieved_state is not None
        assert registered_state is retrieved_state
        assert retrieved_state.initialized is False
        assert retrieved_state.capabilities is None

        assert manager.server_count() == 1

    def test_get_does_not_raise_if_server_not_registered(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"

        # Act & Assert
        assert manager.get_server(server_id) is None

    def test_get_ids_returns_list_of_server_ids(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        server_id2 = "test-server-2"

        # Act
        manager.register_server(server_id)
        manager.register_server(server_id2)

        id_list = manager.get_server_ids()

        # Assert
        assert len(id_list) == 2
        assert server_id in id_list
        assert server_id2 in id_list

    def test_register_server_twice_overwrites_state(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"

        # Act
        first_state = manager.register_server(server_id)
        second_state = manager.register_server(server_id)
        retrieved_state = manager.get_server(server_id)

        # Assert
        assert first_state is not second_state
        assert retrieved_state is second_state

    def test_initialize_registered_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        manager.register_server(server_id)

        capabilities = ServerCapabilities()
        info = Implementation(name="test-server", version="1.0.0")
        protocol_version = PROTOCOL_VERSION
        instructions = "Test instructions"

        # Act
        manager.initialize_server(
            server_id, capabilities, info, protocol_version, instructions
        )
        server_state = manager.get_server(server_id)

        # Assert
        assert server_state is not None
        assert server_state.initialized is True
        assert server_state.capabilities is capabilities
        assert server_state.info is info
        assert server_state.protocol_version == protocol_version
        assert server_state.instructions == instructions

    def test_initialize_unregistered_server_auto_registers(self):
        # Arrange
        manager = ServerManager()
        server_id = "new-server"
        capabilities = ServerCapabilities()
        info = Implementation(name="new-server", version="1.0.0")
        protocol_version = PROTOCOL_VERSION

        # Act
        manager.initialize_server(server_id, capabilities, info, protocol_version)
        server_state = manager.get_server(server_id)

        # Assert
        assert server_state is not None
        assert server_state.initialized is True
        assert server_state.capabilities is capabilities

    def test_is_protocol_initialized_returns_correct_status(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"

        # Assert - Before registration
        assert not manager.is_protocol_initialized(server_id)

        # Act & Assert - After registration but before initialization
        manager.register_server(server_id)
        assert not manager.is_protocol_initialized(server_id)

        # Act & Assert - After initialization
        capabilities = ServerCapabilities()
        info = Implementation(name="test-server", version="1.0.0")
        manager.initialize_server(server_id, capabilities, info, PROTOCOL_VERSION)
        assert manager.is_protocol_initialized(server_id)


class TestOutboundRequests:
    async def test_track_request_to_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        request_id = "req-123"

        manager.register_server(server_id)

        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        # Act
        manager.track_request_to_server(server_id, request_id, request, future)

        # Assert
        server_state = manager.get_server(server_id)
        assert server_state is not None
        assert request_id in server_state.requests_to_server

        tracked_request, tracked_future = server_state.requests_to_server[request_id]
        assert tracked_request is request
        assert tracked_future is future

    async def test_track_request_to_server_raises_for_unregistered_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "nonexistent-server"
        request_id = "req-123"

        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        # Act & Assert
        with pytest.raises(ValueError):
            manager.track_request_to_server(server_id, request_id, request, future)

    async def test_untrack_request_to_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        request_id = "req-123"

        manager.register_server(server_id)

        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        # Track first, then untrack
        manager.track_request_to_server(server_id, request_id, request, future)
        assert manager.get_request_to_server(server_id, request_id) is not None

        # Act
        result = manager.untrack_request_to_server(server_id, request_id)

        # Assert
        assert result is not None
        untracked_request, untracked_future = result
        assert untracked_request is request
        assert untracked_future is future

        # Verify it's actually removed from tracking
        server_state = manager.get_server(server_id)
        assert request_id not in server_state.requests_to_server

    async def test_untrack_request_to_server_raises_for_unregistered_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "nonexistent-server"
        request_id = "req-123"

        # Act & Assert
        with pytest.raises(ValueError):
            manager.untrack_request_to_server(server_id, request_id)

    async def test_get_request_to_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        request_id = "req-123"

        manager.register_server(server_id)

        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        manager.track_request_to_server(server_id, request_id, request, future)
        # Act
        result = manager.get_request_to_server(server_id, request_id)

        # Assert
        assert result is not None
        retrieved_request, retrieved_future = result
        assert retrieved_request is request

    async def test_get_request_to_server_returns_none_for_unregistered_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "nonexistent-server"
        request_id = "req-123"

        # Act
        result = manager.get_request_to_server(server_id, request_id)

        # Assert
        assert result is None

    async def test_get_request_to_server_returns_none_for_nonexistent_request(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        request_id = "nonexistent-request"

        manager.register_server(server_id)

        # Act
        result = manager.get_request_to_server(server_id, request_id)

        # Assert
        assert result is None

    async def test_resolve_request_to_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        request_id = "req-123"

        manager.register_server(server_id)

        request = PingRequest()
        future = asyncio.Future[Result | Error]()

        # Track the request first
        manager.track_request_to_server(server_id, request_id, request, future)

        # Create a result to resolve with
        result = EmptyResult()

        # Act
        manager.resolve_request_to_server(server_id, request_id, result)

        # Assert
        assert future.done()
        assert future.result() is result

        # Verify request is removed from tracking
        server_state = manager.get_server(server_id)
        assert request_id not in server_state.requests_to_server

    async def test_resolve_does_nothing_if_server_not_found(self):
        # Arrange
        manager = ServerManager()
        server_id = "nonexistent-server"
        request_id = "req-123"

        # Verify server doesn't exist
        assert manager.get_server(server_id) is None

        result = EmptyResult()

        # Act & Assert - no error is raised
        manager.resolve_request_to_server(server_id, request_id, result)
        # If we get here without an exception, the test passes

    async def test_resolve_does_nothing_if_request_not_found(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        request_id = "nonexistent-request"

        manager.register_server(server_id)

        # Verify request doesn't exist
        assert manager.get_request_to_server(server_id, request_id) is None

        result = EmptyResult()

        # Act & Assert - no error is raised
        manager.resolve_request_to_server(server_id, request_id, result)
        # If we get here without an exception, the test passes


class TestInboundRequests:
    async def test_track_request_from_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        request_id = "req-123"

        manager.register_server(server_id)

        # Create mock request and task
        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(0))  # Simple task for testing

        # Act
        manager.track_request_from_server(server_id, request_id, request, task)

        # Assert
        server_state = manager.get_server(server_id)
        assert server_state is not None
        assert request_id in server_state.requests_from_server

        tracked_request, tracked_task = server_state.requests_from_server[request_id]
        assert tracked_request is request
        assert tracked_task is task

        # Cleanup
        task.cancel()

    async def test_track_request_from_server_raises_for_unregistered_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "nonexistent-server"
        request_id = "req-123"

        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(0))  # Simple task for testing

        # Act & Assert
        with pytest.raises(ValueError):
            manager.track_request_from_server(server_id, request_id, request, task)

        # Cleanup
        task.cancel()

    async def test_untrack_request_from_server(self):
        """Test that we can successfully untrack a request from a server."""
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        request_id = "req-123"

        manager.register_server(server_id)

        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(0))

        # Track first, then untrack
        manager.track_request_from_server(server_id, request_id, request, task)
        assert manager.get_request_from_server(server_id, request_id) is not None

        # Act
        result = manager.untrack_request_from_server(server_id, request_id)

        # Assert
        assert result is not None
        untracked_request, untracked_task = result
        assert untracked_request is request
        assert untracked_task is task

        # Verify it's actually removed from tracking
        server_state = manager.get_server(server_id)
        assert request_id not in server_state.requests_from_server

        # Cleanup
        task.cancel()

    async def test_untrack_request_from_server_raises_for_unregistered_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "nonexistent-server"
        request_id = "req-123"

        # Act & Assert
        with pytest.raises(ValueError):
            manager.untrack_request_from_server(server_id, request_id)

    async def test_get_request_from_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        request_id = "req-123"

        manager.register_server(server_id)

        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(0))

        # Track the request first
        manager.track_request_from_server(server_id, request_id, request, task)

        # Act
        result = manager.get_request_from_server(server_id, request_id)

        # Assert
        assert result is not None
        retrieved_request, retrieved_task = result
        assert retrieved_request is request
        assert retrieved_task is task

        # Cleanup
        task.cancel()

    async def test_get_request_from_server_returns_none_for_unregistered_server(self):
        # Arrange
        manager = ServerManager()
        server_id = "nonexistent-server"
        request_id = "req-123"

        # Act
        result = manager.get_request_from_server(server_id, request_id)

        # Assert
        assert result is None

    async def test_get_request_from_server_returns_none_for_nonexistent_request(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        request_id = "nonexistent-request"

        manager.register_server(server_id)

        # Act
        result = manager.get_request_from_server(server_id, request_id)

        # Assert
        assert result is None


class TestCleanup:
    async def test_cleanup_server(self):
        """Test that cleanup_server properly cleans up all server state."""
        # Arrange
        manager = ServerManager()
        server_id = "test-server"

        manager.register_server(server_id)

        # Set up inbound request tracking
        inbound_request = PingRequest()
        inbound_task = asyncio.create_task(asyncio.sleep(10))  # Long-running task
        manager.track_request_from_server(
            server_id, "inbound-123", inbound_request, inbound_task
        )

        # Set up outbound request tracking
        outbound_request = PingRequest()
        outbound_future = asyncio.Future[Result | Error]()
        manager.track_request_to_server(
            server_id, "outbound-456", outbound_request, outbound_future
        )

        # Verify setup
        assert manager.get_server(server_id) is not None
        assert not inbound_task.cancelled()
        assert not outbound_future.done()

        # Act
        manager.cleanup_server(server_id)

        # Assert
        # Server should be removed from tracking
        assert manager.get_server(server_id) is None

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

    async def test_cleanup_all_servers(self):
        """Test that cleanup_all_servers cleans up multiple servers."""
        # Arrange
        manager = ServerManager()
        manager.register_server("server-1")
        manager.register_server("server-2")

        # Act
        manager.cleanup_all_servers()

        # Assert
        assert manager.get_server_ids() == []

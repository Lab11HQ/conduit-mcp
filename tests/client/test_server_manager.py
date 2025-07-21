import asyncio

import pytest

from conduit.client.server_manager import ServerManager, ServerState
from conduit.protocol.base import PROTOCOL_VERSION, Error
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


class TestOutboundRequestTracking:
    async def test_track_request_validates_server_exists(self):
        # Arrange
        manager = ServerManager()

        # Act & Assert
        with pytest.raises(ValueError):
            await manager.track_request_to_server(
                "nonexistent", "req-1", PingRequest(), asyncio.Future()
            )

    async def test_track_request_delegates_to_tracker(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        manager.register_server(server_id)

        request = PingRequest()
        future = asyncio.Future()

        # Act
        manager.track_request_to_server(server_id, "req-1", request, future)

        # Assert - verify it's in the tracker
        result = manager.request_tracker.get_outbound_request(server_id, "req-1")
        assert result is not None
        tracked_request, tracked_future = result
        assert tracked_request is request
        assert tracked_future is future

    async def test_resolve_request_delegates_to_tracker(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        manager.register_server(server_id)

        # Track a request
        request = PingRequest()
        future = asyncio.Future()
        manager.track_request_to_server(server_id, "req-1", request, future)
        assert (
            manager.request_tracker.get_outbound_request(server_id, "req-1") is not None
        )

        # Act
        result = EmptyResult()
        manager.resolve_request_to_server(server_id, "req-1", result)

        # Assert
        assert future.done()
        assert future.result() is result
        assert manager.request_tracker.get_outbound_request(server_id, "req-1") is None

    async def test_remove_request_delegates_to_tracker(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        manager.register_server(server_id)

        request = PingRequest()
        future = asyncio.Future()
        manager.track_request_to_server(server_id, "req-1", request, future)
        assert (
            manager.request_tracker.get_outbound_request(server_id, "req-1") is not None
        )

        # Act
        manager.remove_request_to_server(server_id, "req-1")

        # Assert
        assert manager.request_tracker.get_outbound_request(server_id, "req-1") is None

        # Assert - future is resolved with error
        assert future.done()
        assert isinstance(future.result(), Error)


class TestInboundRequestTracking:
    async def test_track_request_validates_server_exists(self):
        # Arrange
        manager = ServerManager()

        task = asyncio.create_task(asyncio.sleep(0.1))

        # Act & Assert
        with pytest.raises(ValueError, match="not registered"):
            manager.track_request_from_server(
                "nonexistent", "req-1", PingRequest(), task
            )

        # Cleanup
        task.cancel()

    async def test_track_request_delegates_to_tracker(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        manager.register_server(server_id)

        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(0.1))

        # Act
        manager.track_request_from_server(server_id, "req-1", request, task)

        # Assert
        result = manager.request_tracker.get_inbound_request(server_id, "req-1")
        assert result is not None
        assert result[0] is request
        assert result[1] is task

        task.cancel()

    async def test_cancel_request_delegates_to_tracker(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        manager.register_server(server_id)

        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(0.1))

        manager.track_request_from_server(server_id, "req-1", request, task)
        assert (
            manager.request_tracker.get_inbound_request(server_id, "req-1") is not None
        )

        # Act
        manager.cancel_request_from_server(server_id, "req-1")

        # Assert
        assert manager.request_tracker.get_inbound_request(server_id, "req-1") is None

        # Verify task is cancelled
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_remove_request_delegates_to_tracker(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        manager.register_server(server_id)

        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(0.1))

        manager.track_request_from_server(server_id, "req-1", request, task)
        assert (
            manager.request_tracker.get_inbound_request(server_id, "req-1") is not None
        )

        # Act
        manager.remove_request_from_server(server_id, "req-1")

        # Assert
        assert manager.request_tracker.get_inbound_request(server_id, "req-1") is None

        # Verify task is cancelled
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestCleanup:
    async def test_cleanup_server_delegates_to_tracker(self):
        # Arrange
        manager = ServerManager()
        server_id = "test-server"
        manager.register_server(server_id)

        # Track some requests
        future = asyncio.Future()
        task = asyncio.create_task(asyncio.sleep(1))

        manager.track_request_to_server(server_id, "out-1", PingRequest(), future)
        manager.track_request_from_server(server_id, "in-1", PingRequest(), task)
        assert (
            manager.request_tracker.get_outbound_request(server_id, "out-1") is not None
        )
        assert (
            manager.request_tracker.get_inbound_request(server_id, "in-1") is not None
        )

        # Act
        manager.cleanup_server(server_id)

        # Assert - requests cleaned up via tracker delegation
        assert manager.request_tracker.get_outbound_request(server_id, "out-1") is None
        assert manager.request_tracker.get_inbound_request(server_id, "in-1") is None

        # Assert - task is cancelled
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Assert - future is resolved with error
        assert future.done()
        assert isinstance(future.result(), Error)

        # Assert - server is removed from manager
        assert manager.get_server(server_id) is None

    async def test_cleanup_all_servers_removes_server_state(self):
        # Arrange
        manager = ServerManager()
        manager.register_server("server-1")
        manager.register_server("server-2")
        assert manager.get_server_ids() is not []

        # Act
        manager.cleanup_all_servers()

        # Assert
        assert manager.get_server_ids() == []

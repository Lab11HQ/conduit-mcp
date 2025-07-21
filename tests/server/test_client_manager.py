import asyncio

import pytest

from conduit.protocol.base import PROTOCOL_VERSION, Error
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


class TestOutboundRequestTracking:
    async def test_track_request_validates_client_exists(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"

        # Act & Assert
        with pytest.raises(ValueError):
            manager.track_request_to_client(
                client_id, "req-1", PingRequest(), asyncio.Future()
            )

    async def test_track_request_delegates_to_tracker(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"
        manager.register_client(client_id)
        request = PingRequest()
        future = asyncio.Future()

        # Act
        manager.track_request_to_client(client_id, "req-1", request, future)

        # Assert - verify it's in the tracker
        result = manager.request_tracker.get_outbound_request(client_id, "req-1")
        assert result is not None
        tracked_request, tracked_future = result
        assert tracked_request is request
        assert tracked_future is future

    async def test_resolve_request_delegates_to_tracker(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"
        manager.register_client(client_id)

        # Track a request
        request = PingRequest()
        future = asyncio.Future()
        manager.track_request_to_client(client_id, "req-1", request, future)
        assert (
            manager.request_tracker.get_outbound_request(client_id, "req-1") is not None
        )

        # Act
        result = EmptyResult()
        manager.resolve_request_to_client(client_id, "req-1", result)

        # Assert - verify it's resolved
        assert future.done()
        assert future.result() is result
        assert manager.request_tracker.get_outbound_request(client_id, "req-1") is None

    async def test_remove_request_delegates_to_tracker(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"
        manager.register_client(client_id)

        request = PingRequest()
        future = asyncio.Future()
        manager.track_request_to_client(client_id, "req-1", request, future)
        assert (
            manager.request_tracker.get_outbound_request(client_id, "req-1") is not None
        )

        # Act
        manager.remove_request_to_client(client_id, "req-1")

        # Assert - verify it's removed
        assert manager.request_tracker.get_outbound_request(client_id, "req-1") is None

        # Assert - future is resolved with error
        assert future.done()
        assert isinstance(future.result(), Error)


class TestInboundRequestTracking:
    async def test_track_request_validates_client_exists(self):
        # Arrange
        manager = ClientManager()

        task = asyncio.create_task(asyncio.sleep(1))

        # Act & Assert
        with pytest.raises(ValueError):
            manager.track_request_from_client(
                "nonexistent", "req-1", PingRequest(), task
            )

        # Cleanup
        task.cancel()

    async def test_track_request_delegates_to_tracker(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"
        manager.register_client(client_id)

        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(1))

        # Act
        manager.track_request_from_client(client_id, "req-1", request, task)

        # Assert - verify it's in the tracker
        result = manager.request_tracker.get_inbound_request(client_id, "req-1")
        assert result is not None
        assert result[0] is request
        assert result[1] is task

        # Cleanup
        task.cancel()

    async def test_cancel_request_delegates_to_tracker(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"
        manager.register_client(client_id)

        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(1))

        manager.track_request_from_client(client_id, "req-1", request, task)
        assert (
            manager.request_tracker.get_inbound_request(client_id, "req-1") is not None
        )

        # Act
        manager.cancel_request_from_client(client_id, "req-1")

        # Assert - verify it's removed
        assert manager.request_tracker.get_inbound_request(client_id, "req-1") is None

        # Verify task is cancelled
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_remove_request_delegates_to_tracker(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"
        manager.register_client(client_id)

        request = PingRequest()
        task = asyncio.create_task(asyncio.sleep(1))

        manager.track_request_from_client(client_id, "req-1", request, task)
        assert (
            manager.request_tracker.get_inbound_request(client_id, "req-1") is not None
        )

        # Act
        manager.remove_request_from_client(client_id, "req-1")

        # Assert - verify it's removed
        assert manager.request_tracker.get_inbound_request(client_id, "req-1") is None

        # Verify task is cancelled
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestCleanup:
    async def test_cleanup_client_delegates_to_tracker(self):
        # Arrange
        manager = ClientManager()
        client_id = "test-client"
        manager.register_client(client_id)

        # Track some requests
        future = asyncio.Future()
        task = asyncio.create_task(asyncio.sleep(1))

        manager.track_request_to_client(client_id, "out-1", PingRequest(), future)
        manager.track_request_from_client(client_id, "in-1", PingRequest(), task)
        assert (
            manager.request_tracker.get_outbound_request(client_id, "out-1") is not None
        )
        assert (
            manager.request_tracker.get_inbound_request(client_id, "in-1") is not None
        )

        # Act
        manager.cleanup_client(client_id)

        # Assert - requests cleaned up via tracker delegation
        assert manager.request_tracker.get_outbound_request(client_id, "out-1") is None
        assert manager.request_tracker.get_inbound_request(client_id, "in-1") is None

        # Assert - task is cancelled
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Assert - future is resolved with error
        assert future.done()
        assert isinstance(future.result(), Error)

    async def test_cleanup_all_clients_removes_client_state(self):
        # Arrange
        manager = ClientManager()
        manager.register_client("client-1")
        manager.register_client("client-2")
        assert manager.get_client_ids() is not []

        # Act
        manager.cleanup_all_clients()

        # Assert
        assert manager.get_client_ids() == []

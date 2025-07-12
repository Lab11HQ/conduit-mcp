import asyncio

import pytest

from conduit.protocol.common import PingRequest


class TestMessageCoordinatorLifecycle:
    async def test_start_is_idempotent(self, coordinator):
        # Arrange
        assert not coordinator.running

        # Act - start multiple times
        await coordinator.start()
        assert coordinator.running

        await coordinator.start()  # Should be safe to call again
        assert coordinator.running

        # Assert - still running after multiple starts
        assert coordinator.running

        # Cleanup
        await coordinator.stop()
        assert not coordinator.running

    async def test_start_requires_open_transport(self, coordinator, mock_transport):
        # Arrange
        await mock_transport.close()
        assert not mock_transport.is_open

        # Act & Assert
        with pytest.raises(ConnectionError, match="transport is closed"):
            await coordinator.start()

    async def test_stop_is_idempotent(self, coordinator):
        # Arrange
        await coordinator.start()
        assert coordinator.running

        # Act - stop multiple times
        await coordinator.stop()
        assert not coordinator.running

        await coordinator.stop()  # Should be safe to call again
        assert not coordinator.running

    async def test_stop_without_start_is_safe(self, coordinator):
        # Arrange
        assert not coordinator.running

        # Act & Assert - should not raise
        await coordinator.stop()
        assert not coordinator.running

    async def test_running_property_reflects_state(self, coordinator):
        # Arrange
        assert not coordinator.running

        # Act & Assert
        await coordinator.start()
        assert coordinator.running

        await coordinator.stop()
        assert not coordinator.running

    async def test_coordinator_handles_transport_failure_gracefully(
        self, coordinator, mock_transport, yield_loop
    ):
        # Arrange
        await coordinator.start()

        # Act - simulate transport failure
        await mock_transport.close()

        await yield_loop()

        # Assert - coordinator should still be cleanly stoppable
        await coordinator.stop()
        assert not coordinator.running

    async def test_multiple_start_stop_cycles(self, coordinator):
        # Arrange & Act - multiple cycles
        for _ in range(3):
            assert not coordinator.running
            await coordinator.start()
            assert coordinator.running
            await coordinator.stop()
            assert not coordinator.running

    async def test_coordinator_can_be_restarted_after_stop(
        self, coordinator, mock_transport, yield_loop
    ):
        """Coordinator can be stopped and restarted and still process messages."""
        # Arrange
        handled_messages = []

        async def tracking_handler(client_message):
            handled_messages.append((client_message.client_id, client_message.payload))

        coordinator._handle_client_message = tracking_handler

        # Act - Start, process message, stop
        await coordinator.start()
        mock_transport.add_client_message(
            "client1", {"jsonrpc": "2.0", "method": "test/before-stop"}
        )
        await yield_loop()  # Let message loop process
        await coordinator.stop()

        # Act - Restart and process another message
        await coordinator.start()
        mock_transport.add_client_message(
            "client1", {"jsonrpc": "2.0", "method": "test/after-restart"}
        )
        await yield_loop()  # Let message loop process

        # Assert - Both phases worked
        assert len(handled_messages) == 2
        assert handled_messages[0][0] == "client1"
        assert handled_messages[0][1]["method"] == "test/before-stop"
        assert handled_messages[1][0] == "client1"
        assert handled_messages[1][1]["method"] == "test/after-restart"

        # Cleanup
        await coordinator.stop()

    async def test_stop_cancels_all_client_requests(
        self, coordinator, client_manager, yield_loop
    ):
        # Arrange
        await coordinator.start()

        # Create mock in-flight tasks for multiple clients
        task1 = asyncio.create_task(asyncio.sleep(10))
        task2 = asyncio.create_task(asyncio.sleep(10))

        # Create mock pending request futures
        future1 = asyncio.Future()
        future2 = asyncio.Future()

        # Register clients with both in-flight and pending requests
        client1 = client_manager.register_client("client1")
        client2 = client_manager.register_client("client2")
        assert client_manager.client_count() == 2

        # In-flight requests (FROM clients TO server)
        client1.requests_from_client["req1"] = task1
        client2.requests_from_client["req2"] = task2

        ping_request = PingRequest()
        client1.requests_to_client["ping1"] = (ping_request, future1)
        client2.requests_to_client["ping2"] = (ping_request, future2)

        # Act
        await coordinator.stop()
        await yield_loop()

        # Assert - both types of requests are cancelled
        assert task1.cancelled()
        assert task2.cancelled()
        assert future1.done()
        assert future2.done()
        assert client_manager.client_count() == 0

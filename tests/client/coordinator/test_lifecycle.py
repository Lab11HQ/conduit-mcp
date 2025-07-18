import asyncio

from conduit.protocol.base import Error
from conduit.protocol.common import PingRequest


class TestMessageCoordinatorLifecycle:
    async def test_start_is_idempotent(self, coordinator):
        # Arrange
        assert not coordinator.running

        # Act - start multiple times
        await coordinator.start()
        assert coordinator.running

        await coordinator.start()  # Should be safe to call again

        # Assert - still running after multiple starts
        assert coordinator.running

        # Cleanup
        await coordinator.stop()
        assert not coordinator.running

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

        async def tracking_handler(server_message):
            handled_messages.append((server_message.server_id, server_message.payload))

        coordinator._route_server_message = tracking_handler

        # Act - Start, process message, stop
        await coordinator.start()
        mock_transport.add_server_message(
            "server1", {"jsonrpc": "2.0", "method": "test/before-stop"}
        )
        await yield_loop()
        await coordinator.stop()

        # Act - Restart and process another message
        await coordinator.start()
        mock_transport.add_server_message(
            "server1", {"jsonrpc": "2.0", "method": "test/after-restart"}
        )
        await yield_loop()

        # Assert - Both phases worked
        assert len(handled_messages) == 2
        assert handled_messages[0][1]["method"] == "test/before-stop"
        assert handled_messages[1][1]["method"] == "test/after-restart"

        # Cleanup
        await coordinator.stop()

    async def test_stop_cancels_all_server_requests(
        self, coordinator, server_manager, yield_loop
    ):
        # Arrange
        await coordinator.start()

        # Create mock in-flight tasks for requests FROM server
        mock_request1 = PingRequest()
        mock_request2 = PingRequest()
        task1 = asyncio.create_task(asyncio.sleep(10))
        task2 = asyncio.create_task(asyncio.sleep(10))

        # Create mock pending request futures for requests TO server
        future1 = asyncio.Future()
        future2 = asyncio.Future()

        # Register servers
        server_manager.register_server("server1")
        server_manager.register_server("server2")
        assert server_manager.server_count() == 2

        # Track requests
        server_manager.track_request_from_server(
            "server1", "req1", mock_request1, task1
        )
        server_manager.track_request_from_server(
            "server2", "req2", mock_request2, task2
        )

        server_manager.track_request_to_server(
            "server1", "ping1", PingRequest(), future1
        )
        server_manager.track_request_to_server(
            "server2", "ping2", PingRequest(), future2
        )

        # Act
        await coordinator.stop()
        await yield_loop()

        # Assert - both types of requests are cancelled/resolved
        for task in [task1, task2]:
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert task1.cancelled()
        assert task2.cancelled()
        assert future1.done()
        assert future2.done()

        # Verify futures were resolved with errors
        result1 = future1.result()
        result2 = future2.result()
        assert isinstance(result1, Error)
        assert isinstance(result2, Error)

        # Assert - servers are cleaned up
        assert server_manager.server_count() == 0
